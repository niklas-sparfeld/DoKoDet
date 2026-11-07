#!/usr/bin/env python3
"""Run correctness and preliminary speed scenarios for catalog and evidence JSON reads."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs/reports/0114-M0_Interactive_UI_Performance_Inventory.json"
MANIFEST = ROOT / "backend/fixtures/interactive-ui-performance/v1/manifest.json"
RECORDING = "cardeventnet-IMG_0650"
UNKNOWN = "22222222-2222-5222-8222-222222222222"
DEFAULT_CACHE = Path.home() / ".cache/doko-detector/interactive-performance"
UI_JSON_PREFIXES = (
    "/v1/recordings",
    "/v1/repository-bundles",
    "/v1/round-analyses",
    "/v1/table-observations",
    "/v1/evidence-packages",
)
MEDIA_PARTS = ("/video", "/thumbnail", "/frames/", "/video-snippet")


@dataclass(frozen=True)
class Scenario:
    name: str
    route: str
    path: str
    status: int
    identity: dict[str, Any] | None = None
    error_code: str | None = None


def scenarios() -> list[Scenario]:
    cases = [
        Scenario("catalog_empty", "/v1/recordings", "/v1/recordings", 200, {"recordings": []}),
        Scenario(
            "catalog_hard", "/v1/recordings", "/v1/recordings", 200, {"recording_id": RECORDING}
        ),
        Scenario(
            "recording_detail_hard",
            "/v1/recordings/{recording_id}",
            f"/v1/recordings/{RECORDING}",
            200,
            {"recording_id": RECORDING},
        ),
        Scenario(
            "recording_detail_missing",
            "/v1/recordings/{recording_id}",
            "/v1/recordings/missing-m3-recording",
            404,
            error_code="recording_not_found",
        ),
        Scenario(
            "repository_bundle_hard",
            "/v1/repository-bundles/{recording_id}",
            f"/v1/repository-bundles/{RECORDING}",
            200,
            {"recording_id": RECORDING},
        ),
        Scenario(
            "analysis_missing",
            "/v1/round-analyses/{analysis_id}",
            f"/v1/round-analyses/{UNKNOWN}",
            404,
            error_code="analysis_not_found",
        ),
        Scenario(
            "counterfactual_missing",
            "/v1/round-analyses/{analysis_id}/counterfactuals/{counterfactual_id}",
            f"/v1/round-analyses/{UNKNOWN}/counterfactuals/{UNKNOWN}",
            404,
            error_code="analysis_not_found",
        ),
        Scenario(
            "timeline_missing",
            "/v1/round-analyses/{analysis_id}/timeline",
            f"/v1/round-analyses/{UNKNOWN}/timeline",
            404,
            error_code="analysis_not_found",
        ),
        Scenario(
            "table_observation_missing",
            "/v1/table-observations/{observation_id}",
            f"/v1/table-observations/{UNKNOWN}",
            404,
            error_code="table_observation_not_found",
        ),
        Scenario(
            "evidence_package_missing",
            "/v1/evidence-packages/{package_id}",
            f"/v1/evidence-packages/{UNKNOWN}",
            404,
            error_code="package_not_found",
        ),
        Scenario(
            "evidence_package_observations_missing",
            "/v1/evidence-packages/{package_id}/table-observations",
            f"/v1/evidence-packages/{UNKNOWN}/table-observations",
            404,
            error_code="package_not_found",
        ),
    ]
    inventory = json.loads(INVENTORY.read_text())
    expected = {
        item["route"]
        for item in inventory["operations"]
        if item["method"] == "GET"
        and item["classification"] == "ui"
        and item["route"].startswith(UI_JSON_PREFIXES)
        and not any(part in item["route"] for part in MEDIA_PARTS)
    }
    covered = {case.route for case in cases}
    if expected != covered:
        missing = sorted(expected - covered)
        extra = sorted(covered - expected)
        raise ValueError(f"catalog/evidence inventory mismatch: missing={missing}, extra={extra}")
    return cases


def _link_hard_snapshot(root: Path, cache: Path) -> None:
    from materialize_interactive_ui_performance_fixtures import validate_hard_snapshot

    validate_hard_snapshot(cache)
    manifest = json.loads(MANIFEST.read_text())
    for asset in manifest["assets"]:
        source = cache / "sha256" / asset["sha256"]
        target = root / asset["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, target)


def _settings(root: Path):
    from dokodetector_backend.config import Settings

    return Settings(
        _env_file=None,
        repository_root=root,
        evidence_root=root / ".runtime",
        operations_root=root / "data/operations",
        repository_intake_root=root / "data/intake/recordings",
        evidence_package_intake_root=root / "data/intake/evidence-packages",
        pending_video_root=root / "data/incoming/videos",
        bonjour_enabled=False,
    )


def _check(case: Scenario, response: httpx.Response) -> str | None:
    if response.status_code != case.status:
        return f"expected HTTP {case.status}; got {response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        return "response is not JSON"
    if case.error_code:
        if payload.get("error", {}).get("code") != case.error_code:
            return f"expected error code {case.error_code}; got {payload.get('error')}"
    elif case.identity:
        for key, value in case.identity.items():
            if key == "recording_id":
                if (
                    not any(row.get(key) == value for row in payload.get("recordings", []))
                    and payload.get(key) != value
                ):
                    return f"recording identity mismatch for {value}"
            elif payload.get(key) != value:
                return f"expected {key}={value!r}; got {payload.get(key)!r}"
    return None


async def _sample(
    client: httpx.AsyncClient,
    case: Scenario,
    timeout: float,
    profile: str,
    batch: int,
    iteration: int,
    warmup: bool,
) -> dict[str, Any]:
    started = time.perf_counter_ns()
    try:
        response = await asyncio.wait_for(client.get(case.path), timeout=timeout)
        body = response.content
        error = _check(case, response)
        return {
            "case": case.name,
            "profile": profile,
            "batch": batch,
            "iteration": iteration,
            "warmup": warmup,
            "duration_ns": time.perf_counter_ns() - started,
            "status_code": response.status_code,
            "response_bytes": len(body),
            "response_sha256": hashlib.sha256(body).hexdigest(),
            "ok": error is None,
            "error": error,
        }
    except Exception as exc:
        body = b""
        return {
            "case": case.name,
            "profile": profile,
            "batch": batch,
            "iteration": iteration,
            "warmup": warmup,
            "duration_ns": time.perf_counter_ns() - started,
            "status_code": 0,
            "response_bytes": 0,
            "response_sha256": hashlib.sha256(body).hexdigest(),
            "ok": False,
            "error": str(exc),
        }


async def _exercise_profile(
    app: Any,
    cases: list[Scenario],
    profile: str,
    batch: int,
    warmups: int,
    repeats: int,
    timeout: float,
    samples: list[dict[str, Any]],
) -> None:
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://m3.local",
            timeout=timeout,
        ) as client,
    ):
        for case in cases:
            for is_warmup, count in ((True, warmups), (False, repeats)):
                for iteration in range(count):
                    samples.append(
                        await _sample(
                            client,
                            case,
                            timeout,
                            profile,
                            batch,
                            iteration,
                            is_warmup,
                        )
                    )


def run(
    *,
    hard_cache: Path | None,
    profiles: tuple[str, ...],
    warmups: int,
    repeats: int,
    batches: int,
    timeout: float,
) -> dict[str, Any]:
    from dokodetector_backend.app import create_app

    cases = scenarios()
    samples: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="doko-ui-catalog-m3-") as temp:
        parent = Path(temp)
        for batch in range(batches):
            for profile in profiles:
                root = parent / f"{profile}-{batch}"
                root.mkdir()
                if profile == "hard":
                    if hard_cache is None:
                        raise ValueError("hard profile requires --hard-cache")
                    _link_hard_snapshot(root, hard_cache)
                app = create_app(_settings(root))

                applicable = [
                    case
                    for case in cases
                    if (profile == "hard" and case.name != "catalog_empty")
                    or (profile == "generated_empty" and case.name == "catalog_empty")
                    or case.error_code
                ]
                asyncio.run(
                    _exercise_profile(
                        app,
                        applicable,
                        profile,
                        batch,
                        warmups,
                        repeats,
                        timeout,
                        samples,
                    )
                )
    by_case: dict[str, list[int]] = {}
    for sample in samples:
        if not sample["warmup"] and sample["ok"]:
            by_case.setdefault(f"{sample['profile']}:{sample['case']}", []).append(
                sample["duration_ns"]
            )
    return {
        "schema_version": "interactive-ui-catalog-read-samples/v1",
        "kind": "preliminary_samples",
        "protocol": {
            "warmups": warmups,
            "repeats": repeats,
            "batches": batches,
            "timeout_seconds": timeout,
            "cache_policy": "fresh isolated app per profile and batch; no media requests",
        },
        "hard_manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "samples": samples,
        "distributions": [
            {
                "case": name,
                "samples": len(values),
                "median_ns": statistics.median(values),
                "max_ns": max(values),
            }
            for name, values in sorted(by_case.items())
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hard-cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--profile", choices=("generated_empty", "hard", "both"), default="both")
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--batches", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.warmups, args.repeats, args.batches) < 1:
        parser.error("warmups, repeats, and batches must be positive")
    profiles = ("generated_empty", "hard") if args.profile == "both" else (args.profile,)
    hard_cache = args.hard_cache if "hard" in profiles else None
    result = run(
        hard_cache=hard_cache,
        profiles=profiles,
        warmups=args.warmups,
        repeats=args.repeats,
        batches=args.batches,
        timeout=args.timeout,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    failed = [sample for sample in result["samples"] if not sample["ok"]]
    print(f"Wrote {len(result['samples'])} samples to {args.output}; failures={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
