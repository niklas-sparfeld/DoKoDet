#!/usr/bin/env python3
"""Count bounded reads for the current recording workspace boundaries."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import profile_0115_application_io as io_profile
import run_interactive_ui_pipeline_read_performance as hard_profile


class _ProfileEventProvider:
    def infer(self, video_path: Path, *, request: object, progress_callback=None):
        del video_path, request, progress_callback
        return {"events": [{"time_s": 0.5, "probability": 0.95}]}


def _install_counters() -> None:
    sys.addaudithook(io_profile._audit)
    io_profile._wrap_decoders()
    from dokodetector_backend.pipeline_node_store import PipelineNodeStore

    counters = (
        ("list_nodes", "node_list_calls"),
        ("history", "history_calls"),
        ("_read_revision", "revision_validations"),
        ("_get_unrecovered", "node_manifest_validations"),
    )
    for name, key in counters:
        original = getattr(PipelineNodeStore, name)

        def wrap(function, counter):
            def counted(self, *args, **kwargs):
                if io_profile._active is not None:
                    io_profile._active[counter] += 1
                    if counter == "revision_validations":
                        io_profile._active["revision_validation_keys"].append(
                            (args[0].node_id, args[1])
                        )
                result = function(self, *args, **kwargs)
                if io_profile._active is not None and counter == "history_calls":
                    io_profile._active["history_revision_records"] += len(result)
                if io_profile._active is not None and counter == "node_list_calls":
                    io_profile._active["enumerated_nodes"] += len(result)
                return result

            return counted

        setattr(PipelineNodeStore, name, wrap(original, key))

    original_glob = Path.glob

    def counted_glob(path: Path, pattern: str, *args: Any, **kwargs: Any):
        result = original_glob(path, pattern, *args, **kwargs)
        if path.name != ".lineage-runs" or io_profile._active is None:
            return result
        matches = list(result)
        if io_profile._active is not None:
            io_profile._active["lineage_enumerations"] += 1
            io_profile._active["lineage_entries_enumerated"] += len(matches)
        return iter(matches)

    Path.glob = counted_glob  # type: ignore[method-assign]


def _summary(state: dict[str, Any], root: Path) -> dict[str, Any]:
    relative = []
    for path in state["reads"]:
        try:
            relative.append(str(path.relative_to(root)))
        except ValueError:
            continue
    revision_reads = [
        path
        for path in state["reads"]
        if "/revisions/" in path.as_posix() and path.name == "revision.json"
    ]
    lineage_reads = [path for path in state["reads"] if ".lineage-runs" in path.parts]
    revision_read_counts = Counter(str(path) for path in revision_reads)
    return {
        "read_opens": len(state["reads"]),
        "unique_read_paths": len(set(relative)),
        "unique_json_paths": len({item for item in relative if item.endswith(".json")}),
        "json_loads": state["stdlib_json_loads"],
        "pydantic_json_decodes": state["pydantic_json_decodes"],
        "domain_parsers": dict(sorted(state["domain_parsers"].items())),
        "node_list_calls": state["node_list_calls"],
        "nodes_enumerated": state["enumerated_nodes"],
        "history_calls": state["history_calls"],
        "history_revision_records": state["history_revision_records"],
        "revision_payload_reads": len(revision_reads),
        "revision_payload_bytes": sum(
            path.stat().st_size for path in revision_reads if path.is_file()
        ),
        "repeated_revision_payload_reads": sum(
            count - 1 for count in revision_read_counts.values()
        ),
        "lineage_record_reads": len(lineage_reads),
        "lineage_enumerations": state["lineage_enumerations"],
        "lineage_entries_enumerated": state["lineage_entries_enumerated"],
        "revision_validations": state["revision_validations"],
        "repeated_revision_validations": sum(
            count - 1 for count in Counter(state["revision_validation_keys"]).values()
        ),
        "node_manifest_validations": state["node_manifest_validations"],
        "read_paths": sorted(set(relative)),
    }


async def _measure(app: Any, root: Path, name: str, method: str, path: str, body=None) -> dict:
    root = root.resolve()
    state = {
        "root": root.resolve(),
        "repo_data": hard_profile.ROOT / "data",
        "repo_runtime": hard_profile.ROOT / ".runtime",
        "reads": [],
        "live_reads": [],
        "stdlib_json_loads": 0,
        "pydantic_json_decodes": 0,
        "domain_parsers": Counter(),
        "node_list_calls": 0,
        "enumerated_nodes": 0,
        "history_calls": 0,
        "history_revision_records": 0,
        "revision_validations": 0,
        "node_manifest_validations": 0,
        "lineage_enumerations": 0,
        "lineage_entries_enumerated": 0,
        "revision_validation_keys": [],
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://m0-profile.local",
        timeout=180,
    ) as client:
        io_profile._active = state
        headers = {"Idempotency-Key": str(uuid4())} if name == "processor_launch" else None
        started = time.perf_counter_ns()
        try:
            response = await client.request(method, path, json=body, headers=headers)
        finally:
            io_profile._active = None
    elapsed = time.perf_counter_ns() - started
    try:
        response_json = response.json()
    except ValueError:
        response_json = None
    return {
        "case": name,
        "method": method,
        "path": path,
        "duration_ns": elapsed,
        "status_code": response.status_code,
        "response_bytes": len(response.content),
        "response_sha256": hashlib.sha256(response.content).hexdigest(),
        **_summary(state, root),
        "diagnostic_codes": sorted(
            {
                item.get("code")
                for item in (response_json or {}).get("diagnostics", [])
                if isinstance(item, dict) and isinstance(item.get("code"), str)
            }
        ),
        "stage_keys": [
            item.get("key")
            for item in (response_json or {}).get("stages", [])
            if isinstance(item, dict)
        ],
        "stage_states": {
            item.get("key"): item.get("state")
            for item in (response_json or {}).get("stages", [])
            if isinstance(item, dict) and isinstance(item.get("key"), str)
        },
        "error": response.text[:500] if response.status_code >= 400 else None,
    }


async def run(root: Path) -> dict:
    from dokodetector_backend.app import create_app

    app = create_app(hard_profile._settings(root), event_provider=_ProfileEventProvider())
    io_profile._wrap_decoders()
    recording = hard_profile.RECORDING
    scenarios = [
        ("catalog", "GET", "/v1/recordings", None),
        ("workspace", "GET", f"/api/recordings/{recording}/pipeline", None),
        (
            "stage",
            "GET",
            f"/api/recordings/{recording}/pipeline?stage=visual_identities",
            None,
        ),
        ("history_graph", "GET", f"/api/recordings/{recording}/pipeline/lineage", None),
        (
            "exact_revision",
            "GET",
            f"/api/pipeline/nodes/{hard_profile.IDENTITY_NODE}/revisions/{hard_profile.IDENTITY_REVISION}",
            None,
        ),
        (
            "empty_stage",
            "GET",
            f"/api/recordings/{recording}/pipeline?stage=table_observations",
            None,
        ),
    ]
    observations = []
    io_profile._active = {
        "root": root.resolve(),
        "repo_data": hard_profile.ROOT / "data",
        "repo_runtime": hard_profile.ROOT / ".runtime",
        "reads": [],
        "live_reads": [],
        "stdlib_json_loads": 0,
        "pydantic_json_decodes": 0,
        "domain_parsers": Counter(),
        "node_list_calls": 0,
        "enumerated_nodes": 0,
        "history_calls": 0,
        "history_revision_records": 0,
        "revision_validations": 0,
        "node_manifest_validations": 0,
        "lineage_enumerations": 0,
        "lineage_entries_enumerated": 0,
        "revision_validation_keys": [],
    }
    try:
        startup_started = time.perf_counter_ns()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://m0-profile.local",
                timeout=180,
            ) as client:
                for path in (
                    "/health/live",
                    "/v1/recordings",
                    f"/api/recordings/{hard_profile.RECORDING}/pipeline",
                ):
                    await client.get(path)
            observations.append(
                {
                    "case": "startup",
                    "duration_ns": time.perf_counter_ns() - startup_started,
                    "measurement_scope": "in-process lifespan plus first useful requests",
                    **_summary(io_profile._active, root.resolve()),
                }
            )
            io_profile._active = None
            for name, method, path, body in scenarios:
                observations.append(await _measure(app, root, name, method, path, body))
            selection_path = (
                root
                / "data/operations/pipeline-nodes/.pipeline-node-selections"
                / recording
                / "visual_identities.json"
            )
            selection_path.parent.mkdir(parents=True, exist_ok=True)
            stale_selection = {
                "schema_version": "pipeline-node-selection/v1",
                "recording_id": recording,
                "content_type": "visual_identities",
                "revision": 1,
                "selected_generated": {
                    "node_id": "missing-growth-fixture-node",
                    "revision_id": "missing-growth-fixture-revision",
                },
                "selected_completed_reference": None,
                "updated_at": "2026-11-09T00:00:00Z",
            }
            if selection_path.exists():
                selection_path.unlink()
            selection_path.write_text(json.dumps(stale_selection, separators=(",", ":")))
            observations.append(
                await _measure(
                    app,
                    root,
                    "stale_selection",
                    "GET",
                    f"/api/recordings/{recording}/pipeline?stage=visual_identities",
                )
            )
            stale_row = observations[-1]
            if "invalid_selection" not in stale_row["diagnostic_codes"]:
                raise RuntimeError(
                    f"persisted stale selection did not produce invalid_selection: {stale_row}"
                )
            observations.append(
                await _measure(
                    app,
                    root,
                    "processor_launch",
                    "POST",
                    "/api/jobs",
                    {
                        "type": "event_processing",
                        "context": {"recording_id": recording},
                        "request": {
                            "run_id": f"0117-m0-{uuid4()}",
                            "implementation": {"name": "m0-profile", "version": "1"},
                            "configuration": {"threshold": 0.5},
                            "extraction_policy": {"policy_id": "m0-profile/v1"},
                        },
                    },
                )
            )
    finally:
        io_profile._active = None
    statuses = {row["case"]: row.get("status_code") for row in observations if "status_code" in row}
    expected = {
        "catalog": 200,
        "workspace": 200,
        "stage": 200,
        "history_graph": 200,
        "exact_revision": 200,
        "empty_stage": 200,
        "processor_launch": 202,
    }
    if any(statuses.get(case) != status for case, status in expected.items()):
        raise RuntimeError(f"boundary response status mismatch: {statuses}")
    empty_row = next(row for row in observations if row["case"] == "empty_stage")
    if empty_row["stage_states"].get("table_observations") != "empty":
        raise RuntimeError("persisted empty stage did not remain empty")
    return {
        "schema_version": "0117-boundary-profile/v1",
        "source_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=hard_profile.ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "hard_manifest_sha256": hashlib.sha256(hard_profile.MANIFEST.read_bytes()).hexdigest(),
        "observations": observations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hard-cache", type=Path, default=hard_profile.DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="doko-0117-boundary-profile-") as temp:
        root = Path(temp)
        hard_profile._link_hard_snapshot(root, args.hard_cache)
        _install_counters()
        result = asyncio.run(run(root))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {len(result['observations'])} boundary profiles to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
