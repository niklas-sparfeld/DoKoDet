#!/usr/bin/env python3
"""Measure and check the inventoried interactive UI JSON reads."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs/reports/0114-M0_Interactive_UI_Performance_Inventory.json"
FIXTURE_MANIFEST = ROOT / "backend/fixtures/interactive-ui-performance/v1/manifest.json"
DEFAULT_HARD_CACHE = Path.home() / ".cache/doko-detector/interactive-performance"
DEFAULT_TIMEOUT = 30.0
DEFAULT_WARMUPS = 5
DEFAULT_REPEATS = 30
DEFAULT_BATCHES = 3

RECORDING = "cardeventnet-IMG_0650"
JOB_ID = str(uuid5(NAMESPACE_URL, "doko-ui-perf-m3-target-0"))
UNKNOWN_ID = "22222222-2222-5222-8222-222222222222"
MAX_IDENTITY_NODE = "e0d2e2fb-53ab-59c5-8991-3aba74f828ae"
MAX_IDENTITY_REVISION = "f78c1e0a-2c0f-5312-98d6-b0b9b6650c0e"
MAX_POLYGON_NODE = "b5090a82-d8ba-5714-a66b-6ee4e4e707f1"
MAX_POLYGON_REVISION = "dd8b1436-cf47-5104-87c6-6b2b0cc4c572"


@dataclass(frozen=True)
class ReadSample:
    case: str
    duration_ns: int
    status_code: int
    expected_status: int
    response_bytes: int
    response_sha256: str
    ok: bool
    error: str | None = None
    iteration: int = 0
    batch: int = 0
    warmup: bool = False
    first_sample: bool = False


def _scenario(
    name: str,
    route: str,
    path: str,
    status: int,
    *,
    query: dict[str, str] | None = None,
    keys: tuple[str, ...] = (),
    error_code: str | None = None,
    error_key: str = "error",
) -> dict[str, Any]:
    return {
        "name": name,
        "route": route,
        "path": path,
        "status": status,
        "query": query or {},
        "keys": keys,
        "error_code": error_code,
        "error_key": error_key,
    }


def read_scenarios() -> list[dict[str, Any]]:
    """Return concrete requests for every inventoried UI JSON read."""
    recording = RECORDING
    scenarios = [
        _scenario(
            "frame_review_queue_unavailable",
            "/api/frame-reviews/0096-M4",
            "/api/frame-reviews/0096-M4",
            503,
            keys=("detail",),
            error_key="detail",
        ),
        _scenario(
            "jobs_history_page",
            "/api/jobs",
            "/api/jobs",
            200,
            query={"scope": "history", "limit": "3"},
            keys=("items", "next_cursor", "queue_revision", "groups"),
        ),
        _scenario(
            "job_detail",
            "/api/jobs/{job_id}",
            f"/api/jobs/{JOB_ID}",
            200,
            keys=("id", "state", "results", "capabilities"),
        ),
        _scenario(
            "job_detail_missing",
            "/api/jobs/{job_id}",
            f"/api/jobs/{UNKNOWN_ID}",
            404,
            error_code="job_not_found",
        ),
        _scenario(
            "job_calibration_preview_wrong_type",
            "/api/jobs/{job_id}/calibration-preview",
            f"/api/jobs/{JOB_ID}/calibration-preview",
            409,
            error_code="calibration_preview_unavailable",
        ),
        _scenario(
            "job_logs_first_page",
            "/api/jobs/{job_id}/logs",
            f"/api/jobs/{JOB_ID}/logs",
            200,
            query={"after": "0", "limit": "10"},
            keys=("entries", "next_after", "truncated_before"),
        ),
        _scenario(
            "job_logs_missing",
            "/api/jobs/{job_id}/logs",
            f"/api/jobs/{UNKNOWN_ID}/logs",
            404,
            error_code="job_not_found",
        ),
        _scenario(
            "node_revision_event",
            "/api/pipeline/nodes/{node_id}/revisions/{revision_id}",
            "/api/pipeline/nodes/5606e120-028e-52d0-9e1a-b1fafdbc23ee/revisions/dd991694-5b35-5bfd-924b-1d84bee6a16c",
            200,
            keys=("node_id", "revision_id", "content", "metadata"),
        ),
        _scenario(
            "node_revision_max_visual_identity",
            "/api/pipeline/nodes/{node_id}/revisions/{revision_id}",
            f"/api/pipeline/nodes/{MAX_IDENTITY_NODE}/revisions/{MAX_IDENTITY_REVISION}",
            200,
            keys=("node_id", "revision_id", "content", "metadata"),
        ),
        _scenario(
            "node_revision_max_visible_card",
            "/api/pipeline/nodes/{node_id}/revisions/{revision_id}",
            f"/api/pipeline/nodes/{MAX_POLYGON_NODE}/revisions/{MAX_POLYGON_REVISION}",
            200,
            keys=("node_id", "revision_id", "content", "metadata"),
        ),
        _scenario(
            "node_revision_reviews",
            "/api/pipeline/nodes/{node_id}/revisions/{revision_id}/reviews",
            "/api/pipeline/nodes/5606e120-028e-52d0-9e1a-b1fafdbc23ee/revisions/dd991694-5b35-5bfd-924b-1d84bee6a16c/reviews",
            200,
        ),
        _scenario(
            "pipeline_workspace_full",
            "/api/recordings/{recording_id}/pipeline",
            f"/api/recordings/{recording}/pipeline",
            200,
            keys=("schema_version", "recording_id", "video", "stages", "diagnostics"),
        ),
        _scenario(
            "pipeline_workspace_stage_query",
            "/api/recordings/{recording_id}/pipeline",
            f"/api/recordings/{recording}/pipeline",
            200,
            query={"stage": "events"},
            keys=("schema_version", "recording_id", "video", "stages", "diagnostics"),
        ),
        _scenario(
            "calibration_refinement_snapshot",
            "/api/recordings/{recording_id}/pipeline/calibration-refinement",
            "/api/recordings/cardeventnet-IMG_0655/pipeline/calibration-refinement",
            404,
            query={
                "proposal_revision_id": (
                    "card-scene-proposal-0086-91x59-IMG_0655-retry-65bb8ec7-attempt-1"
                )
            },
            error_code="calibration_refinement_not_found",
        ),
        _scenario(
            "pipeline_calibration_revision_missing",
            "/api/recordings/{recording_id}/pipeline/calibrations/{calibration_revision_id}",
            f"/api/recordings/{recording}/pipeline/calibrations/{UNKNOWN_ID}",
            404,
            error_code="calibration_not_found",
        ),
        _scenario(
            "pipeline_events_runs",
            "/api/recordings/{recording_id}/pipeline/events",
            f"/api/recordings/{recording}/pipeline/events",
            200,
            keys=("recording_id", "runs"),
        ),
        _scenario(
            "pipeline_events_selection",
            "/api/recordings/{recording_id}/pipeline/events/selection",
            f"/api/recordings/{recording}/pipeline/events/selection",
            200,
            keys=("recording_id", "selection"),
        ),
        _scenario(
            "pipeline_event_result_missing",
            "/api/recordings/{recording_id}/pipeline/events/{run_id}/result",
            f"/api/recordings/{recording}/pipeline/events/{UNKNOWN_ID}/result",
            404,
            error_code="pipeline_run_not_found",
        ),
        _scenario(
            "pipeline_lineage",
            "/api/recordings/{recording_id}/pipeline/lineage",
            f"/api/recordings/{recording}/pipeline/lineage",
            200,
            keys=("schema_version", "nodes", "edges"),
        ),
        _scenario(
            "pipeline_observation_runs",
            "/api/recordings/{recording_id}/pipeline/observations",
            f"/api/recordings/{recording}/pipeline/observations",
            200,
            keys=("recording_id", "runs"),
        ),
        _scenario(
            "pipeline_observation_selection",
            "/api/recordings/{recording_id}/pipeline/observations/selection",
            f"/api/recordings/{recording}/pipeline/observations/selection",
            200,
            keys=("recording_id", "selection"),
        ),
        _scenario(
            "pipeline_observation_result_missing",
            "/api/recordings/{recording_id}/pipeline/observations/{run_id}/result",
            f"/api/recordings/{recording}/pipeline/observations/{UNKNOWN_ID}/result",
            404,
            error_code="pipeline_run_not_found",
        ),
        _scenario(
            "pipeline_proposed_scene_runs",
            "/api/recordings/{recording_id}/pipeline/proposed-card-scenes",
            f"/api/recordings/{recording}/pipeline/proposed-card-scenes",
            200,
            keys=("recording_id", "runs"),
        ),
        _scenario(
            "pipeline_proposed_scene_result_missing",
            "/api/recordings/{recording_id}/pipeline/proposed-card-scenes/{run_id}/result",
            f"/api/recordings/{recording}/pipeline/proposed-card-scenes/{UNKNOWN_ID}/result",
            404,
            error_code="pipeline_run_not_found",
        ),
        _scenario(
            "pipeline_run_missing",
            "/api/recordings/{recording_id}/pipeline/runs/{run_id}",
            f"/api/recordings/{recording}/pipeline/runs/{UNKNOWN_ID}",
            404,
            error_code="pipeline_run_not_found",
        ),
        _scenario(
            "pipeline_visible_card_runs",
            "/api/recordings/{recording_id}/pipeline/visible-cards",
            f"/api/recordings/{recording}/pipeline/visible-cards",
            200,
            keys=("recording_id", "runs"),
        ),
        _scenario(
            "pipeline_visible_card_selection",
            "/api/recordings/{recording_id}/pipeline/visible-cards/selection",
            f"/api/recordings/{recording}/pipeline/visible-cards/selection",
            200,
            keys=("recording_id", "selection"),
        ),
        _scenario(
            "pipeline_visible_card_result_missing",
            "/api/recordings/{recording_id}/pipeline/visible-cards/{run_id}/result",
            f"/api/recordings/{recording}/pipeline/visible-cards/{UNKNOWN_ID}/result",
            404,
            error_code="pipeline_run_not_found",
        ),
        _scenario(
            "pipeline_visual_identity_runs",
            "/api/recordings/{recording_id}/pipeline/visual-identities",
            f"/api/recordings/{recording}/pipeline/visual-identities",
            200,
            keys=("recording_id", "runs"),
        ),
        _scenario(
            "pipeline_visual_identity_crop_inputs",
            "/api/recordings/{recording_id}/pipeline/visual-identities/proposed-crop-inputs",
            f"/api/recordings/{recording}/pipeline/visual-identities/proposed-crop-inputs",
            200,
            keys=("recording_id", "inputs"),
        ),
        _scenario(
            "pipeline_visual_identity_selection",
            "/api/recordings/{recording_id}/pipeline/visual-identities/selection",
            f"/api/recordings/{recording}/pipeline/visual-identities/selection",
            200,
            keys=("recording_id", "selection"),
        ),
        _scenario(
            "pipeline_visual_identity_result_missing",
            "/api/recordings/{recording_id}/pipeline/visual-identities/{run_id}/result",
            f"/api/recordings/{recording}/pipeline/visual-identities/{UNKNOWN_ID}/result",
            404,
            error_code="pipeline_run_not_found",
        ),
        _scenario(
            "evidence_package_missing",
            "/v1/evidence-packages/{package_id}",
            f"/v1/evidence-packages/{UNKNOWN_ID}",
            404,
            error_code="package_not_found",
        ),
        _scenario(
            "evidence_package_observations_missing",
            "/v1/evidence-packages/{package_id}/table-observations",
            f"/v1/evidence-packages/{UNKNOWN_ID}/table-observations",
            404,
            error_code="package_not_found",
        ),
        _scenario(
            "recordings_catalog", "/v1/recordings", "/v1/recordings", 200, keys=("recordings",)
        ),
        _scenario(
            "recording_detail",
            "/v1/recordings/{recording_id}",
            f"/v1/recordings/{recording}",
            200,
            keys=("recording_id", "source", "video", "analyses"),
        ),
        _scenario(
            "repository_bundle",
            "/v1/repository-bundles/{recording_id}",
            f"/v1/repository-bundles/{recording}",
            200,
            keys=("recording_id", "files"),
        ),
        _scenario(
            "round_analysis_missing",
            "/v1/round-analyses/{analysis_id}",
            f"/v1/round-analyses/{UNKNOWN_ID}",
            404,
            error_code="analysis_not_found",
        ),
        _scenario(
            "counterfactual_missing",
            "/v1/round-analyses/{analysis_id}/counterfactuals/{counterfactual_id}",
            f"/v1/round-analyses/{UNKNOWN_ID}/counterfactuals/{UNKNOWN_ID}",
            404,
            error_code="analysis_not_found",
        ),
        _scenario(
            "round_analysis_timeline_missing",
            "/v1/round-analyses/{analysis_id}/timeline",
            f"/v1/round-analyses/{UNKNOWN_ID}/timeline",
            404,
            error_code="analysis_not_found",
        ),
        _scenario(
            "table_observation_missing",
            "/v1/table-observations/{observation_id}",
            f"/v1/table-observations/{UNKNOWN_ID}",
            404,
            error_code="table_observation_not_found",
        ),
    ]
    expected = {
        operation["route"]
        for operation in json.loads(INVENTORY.read_text())["operations"]
        if operation["method"] == "GET"
        and operation["classification"] == "ui"
        and not any(
            token in operation["route"]
            for token in ("/video", "thumbnail", "/frames/", "derived-views/")
        )
    }
    covered = {case["route"] for case in scenarios}
    if expected != covered:
        raise ValueError(
            f"JSON read inventory mismatch: uncovered={sorted(expected - covered)}, "
            f"unclassified={sorted(covered - expected)}"
        )
    return scenarios


def _link_hard_snapshot(root: Path, cache: Path) -> dict[str, Any]:
    manifest = json.loads(FIXTURE_MANIFEST.read_text())
    for asset in manifest["assets"]:
        source = cache / "sha256" / asset["sha256"]
        target = root / asset["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, target)
    return manifest


def _seed_jobs(root: Path, count: int) -> str:
    """Write terminal Job model records for stable history and unrelated-growth cases."""
    from dokodetector_backend.job_store import Intent, Job, JobRequest, _digest, _mapping_digest

    jobs_root = root / "data/operations/jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    intents_root = jobs_root / "intents"
    intents_root.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 11, 7, tzinfo=UTC)
    target_job_id = ""
    for index in range(count):
        is_target = index < 6
        recording_id = RECORDING if is_target else f"perf-unrelated-{index:05d}"
        request = JobRequest(
            type="fake",
            context={"recording_id": recording_id},
            request={"input": f"m3-job-{index:07d}"},
        )
        job_id = str(uuid5(NAMESPACE_URL, f"doko-ui-perf-m3-target-{index}"))
        if index == 0:
            target_job_id = job_id
        state = "failed" if index % 2 == 0 else "succeeded"
        created = (now + timedelta(microseconds=index)).isoformat()
        job = Job(
            id=job_id,
            type=request.type,
            label="M3 performance history fixture",
            context=request.context,
            request=request.request,
            idempotency_key=str(uuid5(NAMESPACE_URL, f"doko-ui-perf-m3-key-{index}")),
            request_hash=_digest(request),
            state=state,
            created_at=created,
            updated_at=created,
            started_at=created,
            finished_at=created,
            correlation_id=f"m3-job-{index:07d}",
        )
        submitted_request = {
            "type": request.type,
            "context": request.context,
            "request": request.request,
        }
        intent = Intent(
            sequence=index + 1,
            job=job,
            submitted_request=submitted_request,
            submitted_hash=_mapping_digest(submitted_request),
            committed=True,
        )
        (intents_root / f"{job_id}.json").write_text(intent.model_dump_json())
        job_path = jobs_root / job_id / "job.json"
        job_path.parent.mkdir(parents=True)
        job_path.write_text(job.model_dump_json())
    return target_job_id


def _make_settings(root: Path) -> Any:
    from dokodetector_backend.config import Settings

    return Settings(
        repository_root=root,
        evidence_root=root / ".runtime",
        operations_root=root / "data/operations",
        repository_intake_root=root / "data/intake/recordings",
        evidence_package_intake_root=root / "data/intake/evidence-packages",
        pending_video_root=root / "data/incoming/videos",
        bonjour_enabled=False,
    )


async def _request_case(
    client: httpx.AsyncClient, case: dict[str, Any], timeout: float
) -> tuple[int, bytes, int, str | None]:
    started = time.perf_counter_ns()
    try:
        response = await asyncio.wait_for(
            client.get(case["path"], params=case["query"]), timeout=timeout
        )
        body = response.content
        error = None
        if response.status_code != case["status"]:
            error = f"expected HTTP {case['status']}, got {response.status_code}"
        try:
            payload = response.json()
        except ValueError:
            payload = None
            error = error or "response body is not JSON"
        if payload is not None and case["status"] < 400:
            missing = [key for key in case["keys"] if key not in payload]
            if missing:
                error = error or f"JSON response is missing keys: {missing}"
        elif payload is not None and case["status"] >= 400:
            if case["error_key"] == "detail":
                if "detail" not in payload:
                    error = error or "expected a JSON detail error"
            else:
                error_data = payload.get(case["error_key"])
                if not isinstance(error_data, dict):
                    error = error or f"JSON error body is missing {case['error_key']}"
                elif case["error_code"] and error_data.get("code") != case["error_code"]:
                    error = (
                        error
                        or f"expected error code {case['error_code']}, got {error_data.get('code')}"
                    )
        return response.status_code, body, time.perf_counter_ns() - started, error
    except Exception as error:
        return 0, b"", time.perf_counter_ns() - started, str(error)


def run_read_performance(
    *,
    hard_cache: Path = DEFAULT_HARD_CACHE,
    repeats: int = DEFAULT_REPEATS,
    warmups: int = DEFAULT_WARMUPS,
    batches: int = DEFAULT_BATCHES,
    timeout: float = DEFAULT_TIMEOUT,
    history_size: int = 300,
) -> dict[str, Any]:
    """Run all inventory reads over hard storage and a grown production job history."""
    from materialize_interactive_ui_performance_fixtures import validate_hard_snapshot
    from run_interactive_ui_performance import _result, _sample_distributions

    from dokodetector_backend.app import create_app

    if history_size < 12:
        raise ValueError("history_size must be at least 12")
    scenarios = read_scenarios()
    validate_hard_snapshot(hard_cache)
    samples = []
    page_checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="doko-ui-read-m3-") as temp:
        work = Path(temp)
        fixture_id = hashlib.sha256(FIXTURE_MANIFEST.read_bytes()).hexdigest()
        for batch in range(batches):
            root = work / f"hard-{batch}"
            root.mkdir()
            manifest = _link_hard_snapshot(root, hard_cache)
            target_job_id = _seed_jobs(root, history_size)
            settings = _make_settings(root)
            app = create_app(settings)
            growth_case = _scenario(
                "job_filtered_history_growth",
                "/api/jobs",
                "/api/jobs",
                200,
                query={"scope": "history", "recording_id": RECORDING, "limit": "10"},
                keys=("items", "next_cursor", "queue_revision", "groups"),
            )
            small_root = work / f"small-{batch}"
            small_root.mkdir()
            _link_hard_snapshot(small_root, hard_cache)
            _seed_jobs(small_root, 12)
            small_app = create_app(_make_settings(small_root))

            async def run_batch(
                batch_index: int = batch,
                app_to_run: Any = app,
                small_app_to_run: Any = small_app,
                target_id: str = target_job_id,
                scenario_list: list[dict[str, Any]] = scenarios,
                current_growth_case: dict[str, Any] = growth_case,
                root_to_run: Path = root,
            ) -> None:
                # Keep first-use samples separate from the warm batch. Fixture setup and
                # application construction are outside the request clock.
                for case in [*scenario_list, current_growth_case]:
                    first_app = create_app(_make_settings(root_to_run))
                    async with (
                        first_app.router.lifespan_context(first_app),
                        httpx.AsyncClient(
                            transport=httpx.ASGITransport(app=first_app),
                            base_url="http://controlled.local",
                            timeout=timeout,
                        ) as first_client,
                    ):
                        status, body, duration, error = await _request_case(
                            first_client, case, timeout
                        )
                    samples.append(
                        ReadSample(
                            case["name"],
                            duration,
                            status,
                            case["status"],
                            len(body),
                            hashlib.sha256(body).hexdigest(),
                            error is None,
                            error,
                            iteration=0,
                            batch=batch_index,
                            first_sample=True,
                        )
                    )

                async with (
                    app_to_run.router.lifespan_context(app_to_run),
                    httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app_to_run),
                        base_url="http://controlled.local",
                        timeout=timeout,
                    ) as client,
                ):
                    # Re-read the paged, filtered history and prove the cursor boundary.
                    first = await client.get(
                        "/api/jobs",
                        params={"scope": "history", "recording_id": RECORDING, "limit": "3"},
                    )
                    first_json = first.json()
                    cursor = first_json.get("next_cursor")
                    second = (
                        await client.get(
                            "/api/jobs",
                            params={
                                "scope": "history",
                                "recording_id": RECORDING,
                                "limit": "3",
                                "cursor": cursor,
                            },
                        )
                        if cursor
                        else None
                    )
                    second_json = second.json() if second else {}
                    first_ids = [job["id"] for job in first_json.get("items", [])]
                    second_ids = [job["id"] for job in second_json.get("items", [])]
                    all_ids = first_ids + second_ids
                    page_checks.append(
                        {
                            "batch": batch_index,
                            "target_job_id": target_id,
                            "first_page_count": len(first_ids),
                            "second_page_count": len(second_ids),
                            "overlap": sorted(set(first_ids) & set(second_ids)),
                            "unique_target_items": len(set(all_ids)),
                            "expected_target_items": 6,
                            "pass": first.status_code == 200
                            and (second is None or second.status_code == 200)
                            and not (set(first_ids) & set(second_ids))
                            and len(set(all_ids)) == 6,
                        }
                    )
                    large_response = await client.get(
                        current_growth_case["path"],
                        params=current_growth_case["query"],
                    )
                    large_target_ids = [job["id"] for job in large_response.json().get("items", [])]
                    large_target_status = large_response.status_code
                    for case in scenario_list:
                        for warmup in (True, False):
                            count = warmups if warmup else repeats
                            for iteration in range(count):
                                status, body, duration, error = await _request_case(
                                    client, case, timeout
                                )
                                samples.append(
                                    ReadSample(
                                        case["name"],
                                        duration,
                                        status,
                                        case["status"],
                                        len(body),
                                        hashlib.sha256(body).hexdigest(),
                                        error is None,
                                        error,
                                        iteration=iteration,
                                        batch=batch_index,
                                        warmup=warmup,
                                    )
                                )

                    for warmup in (True, False):
                        count = warmups if warmup else repeats
                        for iteration in range(count):
                            status, body, duration, error = await _request_case(
                                client, current_growth_case, timeout
                            )
                            samples.append(
                                ReadSample(
                                    "job_filtered_history_large",
                                    duration,
                                    status,
                                    current_growth_case["status"],
                                    len(body),
                                    hashlib.sha256(body).hexdigest(),
                                    error is None,
                                    error,
                                    iteration=iteration,
                                    batch=batch_index,
                                    warmup=warmup,
                                )
                            )

                async with (
                    small_app_to_run.router.lifespan_context(small_app_to_run),
                    httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=small_app_to_run),
                        base_url="http://controlled.local",
                        timeout=timeout,
                    ) as small_client,
                ):
                    status, body, duration, error = await _request_case(
                        small_client, current_growth_case, timeout
                    )
                    samples.append(
                        ReadSample(
                            "job_filtered_history_small",
                            duration,
                            status,
                            current_growth_case["status"],
                            len(body),
                            hashlib.sha256(body).hexdigest(),
                            error is None,
                            error,
                            iteration=0,
                            batch=batch_index,
                            first_sample=True,
                        )
                    )
                    for warmup in (True, False):
                        count = warmups if warmup else repeats
                        for iteration in range(count):
                            status, body, duration, error = await _request_case(
                                small_client, current_growth_case, timeout
                            )
                            samples.append(
                                ReadSample(
                                    "job_filtered_history_small",
                                    duration,
                                    status,
                                    current_growth_case["status"],
                                    len(body),
                                    hashlib.sha256(body).hexdigest(),
                                    error is None,
                                    error,
                                    iteration=iteration,
                                    batch=batch_index,
                                    warmup=warmup,
                                )
                            )
                    small_response = await small_client.get(
                        current_growth_case["path"],
                        params=current_growth_case["query"],
                    )
                    small_items = [job["id"] for job in small_response.json().get("items", [])]
                    page_checks.append(
                        {
                            "batch": batch_index,
                            "kind": "unrelated_resource_growth",
                            "small_job_count": 12,
                            "large_job_count": history_size,
                            "small_target_ids": small_items,
                            "large_target_ids": large_target_ids,
                            "pass": small_response.status_code == large_target_status == 200
                            and small_items == large_target_ids
                            and len(small_items) == 6,
                        }
                    )

            asyncio.run(run_batch())

        result = _result(
            "controlled_ui_json_reads",
            {
                "profile": "m1_hard_snapshot",
                "manifest_sha256": fixture_id,
                "job_history": history_size,
            },
            samples,
            protocol={
                "fixture_sizes": {
                    "hard_assets": len(manifest["assets"]),
                    "hard_bytes": sum(asset["byte_length"] for asset in manifest["assets"]),
                    "job_records": history_size,
                    "target_recording_jobs": 6,
                },
                "warmups": warmups,
                "repeats": repeats,
                "batches": batches,
                "first_sample_per_case_per_batch": 1,
                "cold_definition": (
                    "fresh app instance and isolated storage per scenario; app construction "
                    "is outside the request clock; no OS filesystem cache claim"
                ),
                "cache_policy": (
                    "derived views and app caches begin empty per batch; warmups then measured "
                    "requests share the batch"
                ),
                "timeout_seconds": timeout,
                "query_variants": [case["name"] for case in scenarios if case["query"]],
                "correctness": (
                    "expected status, JSON parse, top-level response shape, and named error "
                    "codes are checked per sample"
                ),
                "pagination_checks": page_checks,
                "unrelated_resource_growth": (
                    "same six filtered target jobs are measured against 12 and history_size jobs"
                ),
                "inventory_routes": sorted({case["route"] for case in scenarios}),
            },
        )
        result["distributions"] = _sample_distributions(
            [sample for sample in result["samples"] if not sample.get("first_sample")]
        )
        return result


def export_result(result: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    csv_path = output.with_suffix(".csv")
    import csv

    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result["samples"][0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(result["samples"])
    summary_path = output.with_suffix(".summary.csv")
    with summary_path.open("w", newline="") as stream:
        summaries = result["distributions"]
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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hard-cache", type=Path, default=DEFAULT_HARD_CACHE)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--batches", type=int, default=DEFAULT_BATCHES)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--history-size", type=int, default=300)
    args = parser.parse_args()
    if args.repeats < 1 or args.warmups < 0 or args.batches < 1 or args.timeout <= 0:
        parser.error("repeats, batches, and timeout must be positive; warmups cannot be negative")
    try:
        result = run_read_performance(
            hard_cache=args.hard_cache,
            repeats=args.repeats,
            warmups=args.warmups,
            batches=args.batches,
            timeout=args.timeout,
            history_size=args.history_size,
        )
    except Exception as error:
        parser.exit(1, f"UI JSON read performance run failed: {error}\n")
    export_result(result, args.output)
    failures = [sample for sample in result["samples"] if not sample["ok"]]
    failures.extend(
        {"case": "job_page_boundary", "error": str(check)}
        for check in result["protocol"]["pagination_checks"]
        if not check["pass"]
    )
    print(f"Wrote {len(result['samples'])} samples to {args.output}")
    if failures:
        print(json.dumps(failures[:20], indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
