#!/usr/bin/env python3
"""Validate a retained M11 corpus and compare it with its frozen local baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RAW_DEFAULT = ROOT / "docs/reports/0114-M11_Baseline_Raw"
BASELINE_DEFAULT = ROOT / "docs/reports/0114-M11_Performance_Baseline.json"
INVENTORY = ROOT / "docs/reports/0114-M0_Interactive_UI_Performance_Inventory.json"
HARD_MANIFEST = ROOT / "backend/fixtures/interactive-ui-performance/v1/manifest.json"
HARD_CACHE_DEFAULT = Path.home() / ".cache/doko-detector/interactive-performance"
SESSION_NAMES = ("session-01", "session-02", "session-03")
TOLERANCE = 0.20
NOISE_FLOOR_NS = {
    "control": 2_000_000,
    "media": 5_000_000,
    "browser": 10_000_000,
    "startup": 25_000_000,
}


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read result file {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"result file is not a JSON object: {path}")
    return value


def _samples(path: Path) -> list[dict[str, Any]]:
    value = _read(path)
    rows = value.get("samples")
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{path}: missing or malformed samples")
    return rows


def _assert_ok(rows: list[dict[str, Any]], label: str) -> None:
    for index, row in enumerate(rows):
        if row.get("ok") is False:
            raise ValueError(f"{label} sample {index} failed: {row.get('error')}")
        status = row.get("status_code", row.get("status"))
        if not isinstance(status, int) or not 200 <= status < 500:
            raise ValueError(f"{label} sample {index} has invalid response status {status!r}")
        size = row.get("response_bytes")
        if not isinstance(size, int) or size < 0:
            raise ValueError(f"{label} sample {index} has invalid response size")
        digest = row.get("response_sha256")
        if digest is not None and (
            not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError(f"{label} sample {index} has invalid response digest")


def _duration_ns(row: dict[str, Any], label: str) -> int:
    value = row.get("duration_ns", row.get("elapsed_ns"))
    if value is None and isinstance(row.get("action_ms"), (int, float)):
        value = round(float(row["action_ms"]) * 1_000_000)
    if not isinstance(value, (int, float)) or value <= 0 or not math.isfinite(value):
        raise ValueError(f"{label}: invalid or missing finite duration")
    return round(value)


def _group(
    groups: dict[str, dict[str, Any]],
    key: str,
    duration: int,
    category: str,
    *,
    minimum: int,
) -> None:
    group = groups.setdefault(key, {"durations_ns": [], "category": category, "minimum": minimum})
    group["durations_ns"].append(duration)
    if group["category"] != category or group["minimum"] != minimum:
        raise ValueError(f"inconsistent grouping contract for {key}")


def _inventory_and_runner_routes(
    results: Path,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], set[str]]]:
    sys.path.insert(0, str(ROOT / "backend/scripts"))
    from run_interactive_ui_catalog_read_performance import scenarios as catalog_scenarios
    from run_interactive_ui_pipeline_read_performance import scenarios as pipeline_scenarios
    from run_interactive_ui_read_performance import read_scenarios

    inventory = _read(INVENTORY).get("operations")
    if not isinstance(inventory, list):
        raise ValueError("M0 inventory has no operations list")
    route_cases: dict[tuple[str, str], set[str]] = defaultdict(set)
    route_specs: list[tuple[str, str, str]] = []
    for case in catalog_scenarios():
        route_specs.append(
            (getattr(case, "method", "GET").upper(), case.route, f"catalog/{case.name}")
        )
    for case in pipeline_scenarios():
        route_specs.append((case.method.upper(), case.route, f"pipeline/{case.name}"))
    for case in read_scenarios():
        route_specs.append(("GET", case["route"], f"jobs/{case['name']}"))
    route_specs.extend(
        [
            ("GET", "/api/jobs", "controlled/jobs_json"),
            ("GET", "/v1/repository-bundles/{recording_id}/video", "controlled/video_range"),
        ]
    )
    for session in SESSION_NAMES:
        for filename in ("interactive-writes.json", "residual-writes.json", "media.json"):
            data = _read(results / session / filename)
            for sample in data.get("samples", []):
                if isinstance(sample, dict) and sample.get("path") and sample.get("method"):
                    case = sample.get("case", "unknown")
                    family = (
                        "writes"
                        if filename == "interactive-writes.json"
                        else ("residual" if filename == "residual-writes.json" else "media")
                    )
                    route_specs.append(
                        (
                            sample["method"].upper(),
                            sample["path"].split("?", 1)[0],
                            f"{family}/{case}",
                        )
                    )

    for method, route, case_key in route_specs:
        route_cases[(method, route)].add(case_key)
    return inventory, route_cases


def _route_matches(template: str, path: str) -> bool:
    template = template.split("?", 1)[0]
    path = path.split("?", 1)[0]
    if template == path:
        return True
    pieces = [
        re.escape(part) if not (part.startswith("{") and part.endswith("}")) else "[^/]+"
        for part in template.strip("/").split("/")
    ]
    return re.fullmatch("/" + "/".join(pieces), path) is not None


def collect(
    results: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, list[str]]]:
    groups: dict[str, dict[str, Any]] = {}
    route_cases: dict[tuple[str, str], set[str]] = defaultdict(set)
    machine: dict[str, Any] | None = None

    sys.path.insert(0, str(ROOT / "backend/scripts"))
    from materialize_interactive_ui_performance_fixtures import validate_hard_snapshot

    verified_assets = validate_hard_snapshot(HARD_CACHE_DEFAULT)
    if len(verified_assets) != 57:
        raise ValueError(f"hard fixture has {len(verified_assets)} verified assets; expected 57")

    def read_file(relative: str) -> dict[str, Any]:
        return _read(results / relative)

    # Loopback startup and first-use samples. Ten fresh processes per startup profile.
    for profile in ("empty", "hard", "recovery"):
        suffix = {"empty": "startup-empty", "hard": "startup-hard", "recovery": "startup-recovery"}[
            profile
        ]
        data = read_file(f"session-01/{suffix}.json")
        runs = data.get("runs")
        artifact_logs = data.get("artifacts", {}).get("trial_logs", [])
        if (
            not isinstance(runs, list)
            or len(runs) != 10
            or any(not isinstance(run, str) for run in runs)
            or len(artifact_logs) != 10
            or any(not Path(path).is_file() for path in artifact_logs)
        ):
            raise ValueError(f"startup {profile}: expected ten clean fresh process runs")
        current_machine = data.get("metadata", {}).get("machine")
        if not isinstance(current_machine, dict):
            raise ValueError(f"startup {profile}: machine profile is missing")
        if machine is None:
            machine = current_machine
        elif machine != current_machine:
            raise ValueError(f"startup {profile}: machine profile differs from other profiles")
        fixture = data.get("metadata", {}).get("fixture", {})
        expected_fixture_profile = {
            "empty": "empty",
            "hard": "hard_populated",
            "recovery": "interrupted_recovery",
        }[profile]
        if fixture.get("profile") != expected_fixture_profile:
            raise ValueError(f"startup {profile}: fixture profile mismatch")
        if (
            profile == "hard"
            and fixture.get("source_manifest_sha256")
            != hashlib.sha256(HARD_MANIFEST.read_bytes()).hexdigest()
        ):
            raise ValueError("startup hard-data manifest mismatch")
        if profile == "recovery" and fixture.get("seed") != 11401:
            raise ValueError("startup recovery fixture seed mismatch")
        rows = data.get("samples")
        if not isinstance(rows, list):
            raise ValueError(f"startup {profile}: samples are missing")
        _assert_ok(rows, f"startup/{profile}")
        expected_cases = {"health_live", "health_ready", "jobs_json", "recordings_first_use"}
        if profile == "hard":
            expected_cases |= {"workspace_first_use", "video_range"}
        if profile == "recovery":
            expected_cases |= {"interrupted_job_recovery"}
        seen_cases = {row.get("case") for row in rows}
        if seen_cases != expected_cases:
            raise ValueError(
                f"startup {profile}: case coverage mismatch {sorted(seen_cases ^ expected_cases)}"
            )
        startup_counts = {
            case: sum(row.get("case") == case for row in rows) for case in expected_cases
        }
        if len(rows) != 10 * len(expected_cases) or any(
            count != 10 for count in startup_counts.values()
        ):
            raise ValueError(f"startup {profile}: expected ten samples for every case")
        for row in rows:
            if row.get("warmup"):
                continue
            if row.get("case") == "video_range" and (
                row.get("status_code") != 206 or row.get("response_bytes", 0) > 65_536
            ):
                raise ValueError("startup hard video range violated its 65,536-byte contract")
            key = f"startup/{profile}/{row['case']}"
            _group(groups, key, _duration_ns(row, key), "startup", minimum=10)
            route = {
                "health_live": ("GET", "/health/live"),
                "health_ready": ("GET", "/health/ready"),
                "jobs_json": ("GET", "/api/jobs"),
                "recordings_first_use": ("GET", "/v1/recordings"),
                "workspace_first_use": ("GET", "/api/recordings/{recording_id}/pipeline"),
                "video_range": ("GET", "/v1/repository-bundles/{recording_id}/video"),
                "interrupted_job_recovery": ("GET", "/api/jobs/{job_id}"),
            }.get(row["case"])
            if route:
                route_cases[route].add(key)

    # Controlled HTTP endpoint batches: 5 warmups and 30 measured samples x 3 batches.
    controlled = read_file("session-01/controlled-hard.json")
    if controlled.get("metadata", {}).get("fixture", {}).get("profile") != "hard":
        raise ValueError("controlled endpoint profile is not the hard fixture")
    if (
        controlled.get("metadata", {}).get("fixture", {}).get("source_manifest_sha256")
        != hashlib.sha256(HARD_MANIFEST.read_bytes()).hexdigest()
    ):
        raise ValueError("controlled endpoint fixture manifest mismatch")
    rows = controlled.get("samples", [])
    _assert_ok(rows, "controlled")
    for case in ("jobs_json", "video_range"):
        all_case_rows = [row for row in rows if row.get("case") == case]
        measured = [row for row in rows if row.get("case") == case and not row.get("warmup")]
        warmups = [row for row in all_case_rows if row.get("warmup")]
        if (
            len(measured) != 90
            or len(warmups) != 15
            or len(all_case_rows) != 105
            or {row.get("batch") for row in measured} != {0, 1, 2}
        ):
            raise ValueError(f"controlled/{case}: expected 90 measured samples in three batches")
        if case == "video_range" and any(
            row.get("status_code") != 206 or row.get("response_bytes", 0) > 65_536
            for row in all_case_rows
        ):
            raise ValueError("controlled hard video range exceeded its 65,536-byte contract")
        for row in measured:
            key = f"controlled/{case}"
            duration = row.get("completion_ns") if case == "video_range" else row.get("duration_ns")
            _group(
                groups,
                key,
                _duration_ns({"duration_ns": duration}, key),
                "media" if case == "video_range" else "control",
                minimum=90,
            )

    # Catalog cases have generated-empty and hard profiles with 30 repeats x 3 batches.
    catalog = read_file("catalog-reads.json")
    if (
        catalog.get("hard_manifest_sha256")
        != hashlib.sha256(HARD_MANIFEST.read_bytes()).hexdigest()
    ):
        raise ValueError("catalog hard-data manifest mismatch")
    rows = catalog.get("samples", [])
    _assert_ok(rows, "catalog")
    catalog_pairs = {(row.get("case"), row.get("profile")) for row in rows}
    from run_interactive_ui_catalog_read_performance import scenarios as catalog_scenarios

    expected_catalog_pairs = {
        (case.name, profile)
        for case in catalog_scenarios()
        for profile in (
            ("generated_empty", "hard")
            if case.error_code
            else (("generated_empty",) if case.name == "catalog_empty" else ("hard",))
        )
    }
    if catalog_pairs != expected_catalog_pairs:
        raise ValueError(
            "catalog case/profile coverage mismatch: "
            f"{sorted(catalog_pairs ^ expected_catalog_pairs)}"
        )
    for case, profile in catalog_pairs:
        all_pair = [row for row in rows if (row.get("case"), row.get("profile")) == (case, profile)]
        measured = [row for row in all_pair if not row.get("warmup")]
        warmups = [row for row in all_pair if row.get("warmup")]
        if (
            len(measured) != 90
            or len(warmups) != 15
            or len(all_pair) != 105
            or {row.get("batch") for row in measured} != {0, 1, 2}
        ):
            raise ValueError(f"catalog/{case}/{profile}: expected 90 measured samples")
        key = f"catalog/{case}/{profile}"
        for row in measured:
            _group(groups, key, _duration_ns(row, key), "control", minimum=90)
    if len(catalog_pairs) != 18:
        raise ValueError(f"catalog: expected 18 case/profile groups, got {len(catalog_pairs)}")
    # The runner's route metadata is the executable source for catalog route coverage.
    for case in catalog_scenarios():
        route_cases[(getattr(case, "method", "GET").upper(), case.route)].add(
            f"catalog/{case.name}/hard"
        )

    # Pipeline M4-M5 corpus uses a process-cold sample plus a warm sequence per case/batch.
    pipeline = read_file("pipeline-reads.json")
    if (
        pipeline.get("fixture_manifest_sha256")
        != hashlib.sha256(HARD_MANIFEST.read_bytes()).hexdigest()
    ):
        raise ValueError("pipeline hard-data manifest mismatch")
    rows = pipeline.get("samples", [])
    if any(row.get("profile") != "hard" for row in rows):
        raise ValueError("pipeline reads must use the hard-data profile")
    _assert_ok(rows, "pipeline")
    case_names = {row.get("case") for row in rows}
    from run_interactive_ui_pipeline_read_performance import scenarios as pipeline_scenarios

    expected_pipeline_cases = {case.name for case in pipeline_scenarios()}
    if case_names != expected_pipeline_cases:
        raise ValueError(
            f"pipeline case coverage mismatch: {sorted(case_names ^ expected_pipeline_cases)}"
        )
    for case in case_names:
        for state, expected in (("cold", 3), ("warm", 90)):
            all_state = [
                row for row in rows if row.get("case") == case and row.get("cache_state") == state
            ]
            measured = [row for row in all_state if not row.get("warmup")]
            warmups = [row for row in all_state if row.get("warmup")]
            if (
                len(measured) != expected
                or (state == "warm" and len(warmups) != 15)
                or (state == "cold" and warmups)
            ):
                raise ValueError(f"pipeline/{case}/{state}: expected {expected} measured samples")
            key = f"pipeline/{case}/{state}"
            for row in measured:
                _group(groups, key, _duration_ns(row, key), "control", minimum=expected)
    for case in pipeline_scenarios():
        route_cases[(case.method.upper(), case.route)].add(f"pipeline/{case.name}/warm")

    # Three independent disposable sessions cover the single-request M6-M9 families.
    file_specs = [
        ("job-reads.json", "jobs", "duration_ns", 15, "control"),
        ("interactive-writes.json", "writes", "duration_ns", 36, "control"),
        ("residual-writes.json", "residual", "duration_ns", 8, "control"),
        ("media.json", "media", "elapsed_ns", 13, "media"),
    ]
    expected_cases: dict[str, set[str]] = {}
    for filename, family, duration_field, expected_count, category in file_specs:
        all_cases: set[str] = set()
        for session in SESSION_NAMES:
            data = read_file(f"{session}/{filename}")
            rows = data.get("samples", [])
            if len(rows) != expected_count:
                raise ValueError(
                    f"{session}/{filename}: expected {expected_count} rows, got {len(rows)}"
                )
            if data.get("all_pass") is False:
                raise ValueError(f"{session}/{filename}: runner correctness gate failed")
            if family == "jobs":
                expected_job_cases = {
                    "history_page_12",
                    "history_page_300",
                    "history_cursor_page_12",
                    "history_cursor_page_300",
                    "job_detail",
                    "job_detail_missing",
                    "calibration_preview_wrong_type",
                    "job_logs_first_page",
                    "job_logs_missing",
                    "calibration_preview_success",
                }
                if {row.get("case") for row in rows} != expected_job_cases:
                    raise ValueError(f"{session}/{filename}: job-read coverage mismatch")
                job_counts = {
                    case: sum(row.get("case") == case for row in rows)
                    for case in expected_job_cases
                }
                if any(
                    count
                    != (
                        2
                        if case
                        in {
                            "job_detail",
                            "job_detail_missing",
                            "calibration_preview_wrong_type",
                            "job_logs_first_page",
                            "job_logs_missing",
                        }
                        else 1
                    )
                    for case, count in job_counts.items()
                ):
                    raise ValueError(f"{session}/{filename}: job-read sample counts differ")
                expected_status = {
                    "job_detail_missing": 404,
                    "calibration_preview_wrong_type": 409,
                    "job_logs_missing": 404,
                }
                if any(
                    row.get("status_code") != expected_status.get(row["case"], 200) for row in rows
                ):
                    raise ValueError(f"{session}/{filename}: unexpected job-read response")
                pagination = data.get("pagination_checks", [])
                if len(pagination) != 2 or any(
                    check.get("pass") is not True for check in pagination
                ):
                    raise ValueError(f"{session}/{filename}: cursor checks failed")
            if family == "writes":
                effects = data.get("durable_effects", [])
                if len(effects) != 14 or any(
                    effect.get("expected") != effect.get("actual") for effect in effects
                ):
                    raise ValueError(f"{session}/{filename}: durable-effect checks are incomplete")
            if family in {"writes", "residual", "media"}:
                for row in rows:
                    expected_status = (
                        404 if row.get("case") == "unregistered_ui_video_url" else None
                    )
                    status = row.get("status_code", row.get("status"))
                    if expected_status is not None and status != expected_status:
                        raise ValueError(f"{session}/{filename}: boundary response changed")
                    if expected_status is None and not 200 <= status < 300:
                        raise ValueError(f"{session}/{filename}: write/media response failed")
            if family == "media":
                _assert_ok(rows, f"{session}/{filename}")
                if any(not 200 <= row.get("status", 0) < 300 for row in rows):
                    raise ValueError(f"{session}/{filename}: media response is not successful")
                ranges = [row for row in rows if row.get("case") == "recording_video_range_64k"]
                if (
                    len(ranges) != 1
                    or ranges[0].get("status") != 206
                    or ranges[0].get("response_bytes", 65_537) > 65_536
                ):
                    raise ValueError(f"{session}/{filename}: bounded video range case is invalid")
            else:
                _assert_ok(rows, f"{session}/{filename}")
            current_cases = {row.get("case") for row in rows}
            # M6 has ten named cases; four of them run at both history sizes.
            if len(current_cases) != expected_count and (
                family != "jobs" or len(current_cases) != 10
            ):
                raise ValueError(f"{session}/{filename}: duplicate or missing named cases")
            if expected_cases.get(family) and current_cases != expected_cases[family]:
                raise ValueError(f"{session}/{filename}: case set differs between sessions")
            expected_cases[family] = current_cases
            all_cases |= current_cases
            for row in rows:
                case = row["case"]
                key = f"{family}/{case}"
                duration = row.get(duration_field)
                _group(
                    groups, key, _duration_ns({"duration_ns": duration}, key), category, minimum=3
                )
                if family == "jobs" and row.get("path"):
                    route_cases[("GET", row["path"].split("?", 1)[0])].add(key)
                if (
                    family in {"writes", "residual", "media"}
                    and row.get("method")
                    and row.get("path")
                ):
                    route_cases[(row["method"].upper(), row["path"].split("?", 1)[0])].add(key)

    # Three browser sessions, each with ten fresh contexts per scenario.
    for session in SESSION_NAMES:
        data = read_file(f"{session}/browser.json")
        rows = data.get("samples", [])
        if len(rows) != 70:
            raise ValueError(f"{session}/browser.json: expected 70 samples")
        fixture = data.get("metadata", {}).get("fixture")
        if not isinstance(fixture, dict) or fixture.get("file_count", 0) < 100:
            raise ValueError(f"{session}/browser.json: generated browser fixture is incomplete")
        video = next(
            (
                item
                for item in fixture.get("files", [])
                if item.get("path") == "data/intake/recordings/recording-both/videos/video-both.mov"
            ),
            None,
        )
        if (
            fixture.get("file_count") != 106
            or fixture.get("byte_count") != 173_838
            or not isinstance(video, dict)
            or video.get("byte_length") != 1_554
            or video.get("sha256")
            != "86a05a58423fd933b515f091bc42d505c454c346a3f70b9f62af62c44124baef"
        ):
            raise ValueError(f"{session}/browser.json: compact fixture profile mismatch")
        expected_scenarios = {
            "recordings_to_workspace",
            "displayed_revision_switch",
            "frame_crop_navigation",
            "review_save",
            "jobs_drawer_history",
            "job_submission_visible_status",
            "controlled_load",
        }
        if {row.get("scenario") for row in rows} != expected_scenarios:
            raise ValueError(f"{session}/browser.json: browser workflow coverage mismatch")
        for scenario in expected_scenarios:
            subset = [row for row in rows if row.get("scenario") == scenario]
            if len(subset) != 10:
                raise ValueError(f"{session}/browser.json: {scenario} needs ten fresh contexts")
            for row in subset:
                if row.get("errors") or not isinstance(row.get("action_ms"), (int, float)):
                    raise ValueError(
                        f"{session}/browser.json: invalid browser response for {scenario}"
                    )
                if scenario == "frame_crop_navigation" and (
                    row.get("range_requests", 0) < 1
                    or not isinstance(row.get("range_response"), dict)
                    or row["range_response"].get("status") != 206
                    or row["range_response"].get("bytes", 65_537) > 65_536
                ):
                    raise ValueError(f"{session}/browser.json: bounded video range is missing")
                key = f"browser/{scenario}"
                _group(groups, key, _duration_ns(row, key), "browser", minimum=30)

    # One budget key for every inventoried UI operation; each key points to executable samples.
    inventory, declared_routes = _inventory_and_runner_routes(results)
    route_groups: dict[str, list[str]] = {}
    for row in inventory:
        if row.get("classification") != "ui":
            continue
        method, route = row.get("method", "").upper(), row.get("route", "")
        matches: set[str] = set()
        for (candidate_method, candidate_route), keys in declared_routes.items():
            if candidate_method == method and _route_matches(route, candidate_route):
                matches |= keys
        for (candidate_method, candidate_route), keys in route_cases.items():
            if candidate_method == method and _route_matches(route, candidate_route):
                matches |= keys
        if not matches:
            raise ValueError(f"UI route has no retained timing case: {method} {route}")
        key = f"api:{method}:{route}"
        row["budget_key"] = key
        route_groups[key] = sorted(group for group in matches if group in groups)
        if not route_groups[key]:
            raise ValueError(f"UI route has no retained budget samples: {method} {route}")

    browser_scenarios = {key.split("/", 1)[1] for key in groups if key.startswith("browser/")}
    if len(browser_scenarios) != 7:
        raise ValueError(
            f"browser coverage must include seven scenarios, found {sorted(browser_scenarios)}"
        )
    if not machine:
        raise ValueError("machine metadata is missing")
    environment = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": machine.get("cpu_count"),
        "hardware_model": subprocess.run(
            ["sysctl", "-n", "hw.model"], check=True, capture_output=True, text=True
        ).stdout.strip(),
        "processor": platform.processor(),
        "hard_manifest_sha256": hashlib.sha256(HARD_MANIFEST.read_bytes()).hexdigest(),
    }
    return environment, groups, route_groups


def _stats(group: dict[str, Any]) -> dict[str, Any]:
    values = sorted(group["durations_ns"])
    median = statistics.median(values)
    p95 = values[min(len(values) - 1, math.ceil(len(values) * 0.95) - 1)]
    deviations = [abs(value - median) for value in values]
    mad = statistics.median(deviations)
    noise = max(NOISE_FLOOR_NS[group["category"]], math.ceil(3 * 1.4826 * mad))
    reference = p95 if len(values) >= 30 else median
    ceiling = math.ceil(reference * (1 + TOLERANCE) + noise)
    return {
        "samples": len(values),
        "median_ns": int(median),
        "p95_ns": int(p95),
        "noise_mad_ns": int(mad),
        "absolute_noise_allowance_ns": noise,
        "relative_tolerance": TOLERANCE,
        "metric": "p95" if len(values) >= 30 else "median",
        "reference_ns": int(reference),
        "ceiling_ns": ceiling,
        "slow_debt": reference > 1_000_000_000,
        "category": group["category"],
    }


def make_baseline(results: Path) -> dict[str, Any]:
    environment, groups, route_groups = collect(results)
    case_budgets = {key: _stats(value) for key, value in sorted(groups.items())}
    route_budgets = {
        key: {
            "groups": linked,
            "ceiling_ns": max(case_budgets[group]["ceiling_ns"] for group in linked),
        }
        for key, linked in sorted(route_groups.items())
    }
    evidence_files = {}
    for path in sorted(results.rglob("*")):
        if (
            path.is_file()
            and "discarded" not in path.relative_to(results).parts
            and ".artifacts" not in path.parts
        ):
            evidence_files[str(path.relative_to(results))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    run_sources = [
        "backend/scripts/run_interactive_ui_performance.py",
        "backend/scripts/run_interactive_ui_catalog_read_performance.py",
        "backend/scripts/run_interactive_ui_pipeline_read_performance.py",
        "backend/scripts/run_interactive_ui_read_performance.py",
        "backend/scripts/run_interactive_ui_job_read_performance.py",
        "backend/scripts/run_interactive_ui_write_performance.py",
        "backend/tests/test_interactive_ui_residual_write_performance.py",
        "backend/scripts/run_interactive_ui_media_performance.py",
        "backend/scripts/run_interactive_ui_browser_performance.py",
        "backend/scripts/interactive_ui_browser_app.py",
        "backend/scripts/materialize_interactive_ui_performance_fixtures.py",
        "backend/scripts/check_interactive_ui_performance_inventory.py",
        "backend/scripts/qualify_interactive_ui_performance.py",
        "backend/tests/test_interactive_ui_catalog_read_performance.py",
        "backend/tests/test_interactive_ui_pipeline_read_performance.py",
        "backend/tests/test_interactive_ui_read_performance.py",
        "backend/tests/test_interactive_ui_write_performance.py",
        "backend/tests/test_interactive_ui_media_performance.py",
        "backend/tests/test_interactive_ui_performance_qualification.py",
        "backend/tests/test_interactive_ui_performance_runner.py",
        "web/tests/e2e-performance/interactive-ui-real-process.spec.ts",
    ]
    source_hashes = {
        relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        for relative in run_sources
    }
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "schema_version": "interactive-ui-performance-baseline/v1",
        "provenance": {
            "commit": commit,
            "source_sha256": source_hashes,
            "raw_file_sha256": evidence_files,
        },
        "environment": environment,
        "protocol": {
            "warmups": 5,
            "measured_repeats_per_batch": 30,
            "independent_batches": 3,
            "startup_fresh_processes_per_profile": 10,
            "browser_fresh_contexts_per_scenario_per_session": 10,
            "finite_request_timeout_seconds": 180,
            "slow_debt_threshold_ns": 1_000_000_000,
            "cold_os_cache": False,
        },
        "cases": case_budgets,
        "ui_routes": route_budgets,
    }


def qualify(results: Path, baseline_path: Path) -> list[str]:
    baseline = _read(baseline_path)
    candidate = make_baseline(results)
    errors: list[str] = []
    if baseline.get("environment") != candidate.get("environment"):
        errors.append("incompatible machine or hard-fixture profile")
    expected = baseline.get("cases", {})
    actual = candidate.get("cases", {})
    if set(actual) != set(expected):
        errors.append(
            f"case coverage differs: missing={sorted(set(expected) - set(actual))}; "
            f"extra={sorted(set(actual) - set(expected))}"
        )
    expected_routes = baseline.get("ui_routes", {})
    actual_routes = candidate.get("ui_routes", {})
    if set(actual_routes) != set(expected_routes):
        missing_routes = sorted(set(expected_routes) - set(actual_routes))
        extra_routes = sorted(set(actual_routes) - set(expected_routes))
        errors.append(f"UI route coverage differs: missing={missing_routes}; extra={extra_routes}")
    for key in sorted(set(expected) & set(actual)):
        baseline_case = expected[key]
        candidate_case = actual[key]
        if candidate_case["samples"] < baseline_case["samples"]:
            errors.append(
                f"{key}: missing samples ({candidate_case['samples']} < {baseline_case['samples']})"
            )
        if candidate_case["reference_ns"] > baseline_case["ceiling_ns"]:
            errors.append(
                f"{key}: {candidate_case['metric']} {candidate_case['reference_ns']} ns "
                f"exceeds ceiling {baseline_case['ceiling_ns']} ns"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=RAW_DEFAULT)
    parser.add_argument("--baseline", type=Path, default=BASELINE_DEFAULT)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="create the frozen baseline from a complete passing corpus",
    )
    args = parser.parse_args()
    try:
        if args.write_baseline:
            baseline = make_baseline(args.results)
            args.baseline.parent.mkdir(parents=True, exist_ok=True)
            args.baseline.write_text(
                json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(
                f"PASS: wrote {len(baseline['cases'])} case budgets and "
                f"{len(baseline['ui_routes'])} UI route budgets to {args.baseline}"
            )
            return 0
        if not args.baseline.is_file():
            raise ValueError(f"baseline is missing: {args.baseline}")
        errors = qualify(args.results, args.baseline)
    except (ValueError, OSError, KeyError, TypeError) as error:
        errors = [str(error)]
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    baseline = _read(args.baseline)
    print(
        f"PASS: {len(baseline['cases'])} performance case budgets and "
        f"{len(baseline['ui_routes'])} UI route budgets"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
