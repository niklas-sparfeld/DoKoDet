#!/usr/bin/env python3
"""Run correctness and preliminary speed cases for pipeline workspace and revision reads."""

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
DEFAULT_CACHE = Path.home() / ".cache/doko-detector/interactive-performance"
RECORDING = "game-2026-08-20-01-001"
IDENTITY_NODE = "e0d2e2fb-53ab-59c5-8991-3aba74f828ae"
IDENTITY_REVISION = "f78c1e0a-2c0f-5312-98d6-b0b9b6650c0e"
POLYGON_NODE = "b5090a82-d8ba-5714-a66b-6ee4e4e707f1"
POLYGON_REVISION = "dd8b1436-cf47-5104-87c6-6b2b0cc4c572"
CALIBRATION_RECORDING = "cardeventnet-IMG_0655"
CALIBRATION_REVISION = "calibration-cd1069b46e30480b057d90b0"
DRAFT_ID = (
    "calibration-draft-card-scene-proposals-card-scene-proposal-0086-91x59-IMG_0655-"
    "retry-65bb8ec7-attempt-1"
)
UNKNOWN = "22222222-2222-5222-8222-222222222222"


@dataclass(frozen=True)
class Scenario:
    name: str
    route: str
    path: str
    status: int
    check: str


def scenarios() -> list[Scenario]:
    cases = [
        Scenario(
            "workspace_full_hard",
            "/api/recordings/{recording_id}/pipeline",
            f"/api/recordings/{RECORDING}/pipeline",
            200,
            "workspace_full",
        ),
        Scenario(
            "workspace_stage_visual_identities_hard",
            "/api/recordings/{recording_id}/pipeline",
            f"/api/recordings/{RECORDING}/pipeline?stage=visual_identities",
            200,
            "workspace_stage",
        ),
        Scenario(
            "workspace_missing",
            "/api/recordings/{recording_id}/pipeline",
            "/api/recordings/missing-m4-recording/pipeline",
            404,
            "recording_missing",
        ),
        Scenario(
            "lineage_hard",
            "/api/recordings/{recording_id}/pipeline/lineage",
            f"/api/recordings/{RECORDING}/pipeline/lineage",
            200,
            "lineage",
        ),
        Scenario(
            "lineage_missing",
            "/api/recordings/{recording_id}/pipeline/lineage",
            "/api/recordings/missing-m4-recording/pipeline/lineage",
            404,
            "recording_missing",
        ),
        Scenario(
            "revision_max_identity_payload",
            "/api/pipeline/nodes/{node_id}/revisions/{revision_id}",
            f"/api/pipeline/nodes/{IDENTITY_NODE}/revisions/{IDENTITY_REVISION}",
            200,
            "identity_revision",
        ),
        Scenario(
            "revision_max_polygon_payload",
            "/api/pipeline/nodes/{node_id}/revisions/{revision_id}",
            f"/api/pipeline/nodes/{POLYGON_NODE}/revisions/{POLYGON_REVISION}",
            200,
            "polygon_revision",
        ),
        Scenario(
            "revision_missing_stale",
            "/api/pipeline/nodes/{node_id}/revisions/{revision_id}",
            f"/api/pipeline/nodes/{IDENTITY_NODE}/revisions/{UNKNOWN}",
            404,
            "node_missing",
        ),
        Scenario(
            "reviews_exact_revision",
            "/api/pipeline/nodes/{node_id}/revisions/{revision_id}/reviews",
            f"/api/pipeline/nodes/{IDENTITY_NODE}/revisions/{IDENTITY_REVISION}/reviews",
            200,
            "reviews",
        ),
        Scenario(
            "reviews_stale_revision",
            "/api/pipeline/nodes/{node_id}/revisions/{revision_id}/reviews",
            f"/api/pipeline/nodes/{IDENTITY_NODE}/revisions/{UNKNOWN}/reviews",
            404,
            "review_missing",
        ),
        Scenario(
            "calibration_draft_invalid_lineage",
            "/api/recordings/{recording_id}/pipeline/calibration-refinement",
            f"/api/recordings/{CALIBRATION_RECORDING}/pipeline/calibration-refinement?proposal_revision_id=7c1657af-01dc-589f-aec0-32b3e733b9f8&draft_id={DRAFT_ID}",
            422,
            "draft_invalid_lineage",
        ),
        Scenario(
            "calibration_draft_missing",
            "/api/recordings/{recording_id}/pipeline/calibration-refinement",
            f"/api/recordings/{CALIBRATION_RECORDING}/pipeline/calibration-refinement?proposal_revision_id={UNKNOWN}&draft_id={UNKNOWN}",
            404,
            "draft_missing",
        ),
        Scenario(
            "calibration_published_snapshot",
            "/api/recordings/{recording_id}/pipeline/calibrations/{calibration_revision_id}",
            f"/api/recordings/{CALIBRATION_RECORDING}/pipeline/calibrations/{CALIBRATION_REVISION}",
            200,
            "calibration",
        ),
        Scenario(
            "calibration_published_missing",
            "/api/recordings/{recording_id}/pipeline/calibrations/{calibration_revision_id}",
            f"/api/recordings/{CALIBRATION_RECORDING}/pipeline/calibrations/{UNKNOWN}",
            404,
            "calibration_missing",
        ),
    ]
    inventory = json.loads(INVENTORY.read_text())
    expected = {
        item["route"]
        for item in inventory["operations"]
        if item["method"] == "GET"
        and item["classification"] == "ui"
        and item["route"] in {case.route for case in cases}
    }
    covered = {case.route for case in cases}
    if expected != covered:
        raise ValueError(
            "pipeline-read inventory mismatch: "
            f"missing={sorted(expected - covered)}, extra={sorted(covered - expected)}"
        )
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
        try:
            detail = response.json().get("error")
        except (ValueError, AttributeError):
            detail = None
        return f"expected HTTP {case.status}; got {response.status_code}; error={detail!r}"
    try:
        payload = response.json()
    except ValueError:
        return "response is not JSON"
    check = case.check
    if check in {
        "recording_missing",
        "node_missing",
        "review_missing",
        "draft_missing",
        "calibration_missing",
    }:
        expected = {
            "recording_missing": "recording_not_found",
            "node_missing": "pipeline_node_not_found",
            "review_missing": "pipeline_node_review_unavailable",
            "draft_missing": "calibration_refinement_not_found",
            "calibration_missing": "calibration_revision_not_found",
        }[check]
        if payload.get("error", {}).get("code") != expected:
            return f"expected error code {expected}; got {payload.get('error')}"
    elif check.startswith("workspace"):
        if (
            payload.get("schema_version") != "pipeline-workspace/v1"
            or payload.get("recording_id") != RECORDING
        ):
            return "workspace schema or recording identity mismatch"
        if len(payload.get("stages", [])) != 5:
            return "workspace does not contain the five declared stages"
        if check == "workspace_stage" and not any(
            stage.get("key") == "visual_identities" for stage in payload["stages"]
        ):
            return "stage-filtered workspace omitted the requested stage"
    elif check == "lineage":
        nodes = payload.get("nodes", [])
        node_ids = {node.get("node_id") for node in nodes}
        revisions = {
            (item.get("node_id"), item.get("revision_id")) for item in payload.get("revisions", [])
        }
        expected_nodes = {IDENTITY_NODE, POLYGON_NODE}
        expected_revisions = {
            (IDENTITY_NODE, IDENTITY_REVISION),
            (POLYGON_NODE, POLYGON_REVISION),
        }
        if not expected_nodes <= node_ids or not expected_revisions <= revisions:
            return "lineage omitted exact fixture nodes or revisions"
        expected_parents = {
            ("b63729af-60c9-54dd-be3f-f6220db3d19c", "c7f4da13-b918-5009-8ff8-5aec7e099cfe"),
            ("29ff4e43-4ade-568a-9e2f-36b95d075067", "391c5a12-d875-5f8e-b5ee-dd6a75f89695"),
        }
        parent_edges = {
            (edge["from"][1], edge["from"][2])
            for edge in payload.get("edges", [])
            if edge.get("kind") == "copied" and edge.get("from", [None])[0] == "revision"
        }
        if not expected_parents <= parent_edges:
            return "lineage omitted exact fixture parent revisions"
    elif check in {"identity_revision", "polygon_revision"}:
        node, revision = (
            (IDENTITY_NODE, IDENTITY_REVISION)
            if check == "identity_revision"
            else (POLYGON_NODE, POLYGON_REVISION)
        )
        if (payload.get("node_id"), payload.get("revision_id")) != (node, revision):
            return "revision node or revision identity mismatch"
        content = payload.get("content", {})
        values = content.get("items", content.get("visible_cards", content.get("identities", [])))
        if not values and len(json.dumps(content)) < 1000:
            return "expected retained maximum-payload revision content"
    elif check == "reviews":
        if not isinstance(payload, list):
            return "reviews response is not a list"
    elif check == "draft":
        if (
            payload.get("draft_id") != DRAFT_ID
            or payload.get("recording_id") != CALIBRATION_RECORDING
        ):
            return "calibration draft identity mismatch"
    elif check == "calibration":
        if (
            payload.get("calibration_revision_id") != CALIBRATION_REVISION
            or payload.get("recording_id") != CALIBRATION_RECORDING
        ):
            return "published calibration identity mismatch"
    return None


async def _exercise(
    app: Any,
    case: Scenario,
    warmups: int,
    repeats: int,
    timeout: float,
    samples: list[dict[str, Any]],
    profile: str,
    batch: int,
) -> None:
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://m4.local", timeout=timeout
        ) as client,
    ):

        async def sample(*, cache_state: str, warmup: bool, iteration: int) -> None:
            started = time.perf_counter_ns()
            try:
                response = await asyncio.wait_for(client.get(case.path), timeout=timeout)
                error = _check(case, response)
                row = {
                    "case": case.name,
                    "profile": profile,
                    "cache_state": cache_state,
                    "batch": batch,
                    "iteration": iteration,
                    "warmup": warmup,
                    "duration_ns": time.perf_counter_ns() - started,
                    "status_code": response.status_code,
                    "response_bytes": len(response.content),
                    "response_sha256": hashlib.sha256(response.content).hexdigest(),
                    "ok": error is None,
                    "error": error,
                }
            except Exception as exc:
                row = {
                    "case": case.name,
                    "profile": profile,
                    "cache_state": cache_state,
                    "batch": batch,
                    "iteration": iteration,
                    "warmup": warmup,
                    "duration_ns": time.perf_counter_ns() - started,
                    "status_code": 0,
                    "response_bytes": 0,
                    "response_sha256": hashlib.sha256(b"").hexdigest(),
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            samples.append(row)

        await sample(cache_state="cold", warmup=False, iteration=0)
        for iteration in range(warmups):
            await sample(cache_state="warm", warmup=True, iteration=iteration)
        for iteration in range(repeats):
            await sample(cache_state="warm", warmup=False, iteration=iteration)


def run(
    *,
    hard_cache: Path,
    warmups: int,
    repeats: int,
    batches: int,
    timeout: float,
    case_names: set[str] | None = None,
) -> dict[str, Any]:
    from dokodetector_backend.app import create_app

    cases = scenarios()
    if case_names is not None:
        cases = [case for case in cases if case.name in case_names]
        if {case.name for case in cases} != case_names:
            raise ValueError(
                f"unknown scenario names: {sorted(case_names - {case.name for case in cases})}"
            )
    samples: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="doko-ui-pipeline-m4-") as temp:
        parent = Path(temp)
        for batch in range(batches):
            root = parent / f"hard-{batch}"
            root.mkdir()
            _link_hard_snapshot(root, hard_cache)
            for case in cases:
                app = create_app(_settings(root))
                asyncio.run(_exercise(app, case, warmups, repeats, timeout, samples, "hard", batch))
    distributions = []
    groups: dict[str, list[int]] = {}
    for sample in samples:
        if not sample["warmup"] and sample["ok"]:
            groups.setdefault(
                f"{sample['profile']}:{sample['case']}:{sample['cache_state']}", []
            ).append(sample["duration_ns"])
    for name, values in sorted(groups.items()):
        distributions.append(
            {
                "case": name,
                "samples": len(values),
                "median_ns": statistics.median(values),
                "max_ns": max(values),
            }
        )
    return {
        "schema_version": "interactive-ui-pipeline-read-samples/v1",
        "kind": "preliminary_samples",
        "protocol": {
            "warmups": warmups,
            "repeats": repeats,
            "batches": batches,
            "timeout_seconds": timeout,
            "cache_policy": "fresh isolated app per batch; first measured request is process-cold, "
            "subsequent requests are warm; OS filesystem cache not flushed",
        },
        "fixture_manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "samples": samples,
        "distributions": distributions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hard-cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--batches", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--case", action="append", help="Run one named case; may be repeated")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.warmups, args.repeats) < 0 or args.batches < 1:
        parser.error("warmups and repeats cannot be negative; batches must be positive")
    result = run(
        hard_cache=args.hard_cache,
        warmups=args.warmups,
        repeats=args.repeats,
        batches=args.batches,
        timeout=args.timeout,
        case_names=None if args.case is None else set(args.case),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    failed = [sample for sample in result["samples"] if not sample["ok"]]
    print(f"Wrote {len(result['samples'])} samples to {args.output}; failures={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
