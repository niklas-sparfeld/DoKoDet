#!/usr/bin/env python3
"""Count application data reads and decoders for selected 0114 hard cases."""

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

import httpx
import run_interactive_ui_pipeline_read_performance as pipeline_profile
from pydantic import BaseModel

DEFAULT_CACHE = Path.home() / ".cache/doko-detector/interactive-performance"
DEFAULT_CASES = {
    "workspace_full_hard",
    "lineage_hard",
    "revision_max_identity_payload",
    "revision_max_polygon_payload",
}
_active: dict[str, Any] | None = None
_requests: list[dict[str, Any]] = []


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if event != "open" or _active is None:
        return
    raw_path, mode, flags = args
    if not isinstance(raw_path, (str, bytes, Path)):
        return
    try:
        path = Path(raw_path).expanduser().resolve()
    except (OSError, TypeError):
        return
    try:
        path.relative_to(_active["root"])
        bucket = "reads"
    except ValueError:
        try:
            path.relative_to(_active["repo_data"])
            bucket = "live_reads"
        except ValueError:
            try:
                path.relative_to(_active["repo_runtime"])
                bucket = "live_reads"
            except ValueError:
                return
    if isinstance(mode, str):
        is_read = "r" in mode or "+" in mode
    else:
        is_read = isinstance(flags, int) and flags & 3 != 1
    if not is_read:
        return
    _active[bucket].append(path)


def _wrap_decoders() -> None:
    """Wrap parsers after app startup so imports are stable and setup is excluded."""
    current_json_loads = json.loads
    if not getattr(current_json_loads, "_profile_0115", False):

        def tracked_json_loads(*args: Any, **kwargs: Any) -> Any:
            if _active is not None:
                _active["stdlib_json_loads"] += 1
            return current_json_loads(*args, **kwargs)

        tracked_json_loads._profile_0115 = True  # type: ignore[attr-defined]
        json.loads = tracked_json_loads  # type: ignore[assignment]

    current_validate_json = BaseModel.model_validate_json
    if not getattr(current_validate_json, "_profile_0115", False):

        def tracked_validate_json(cls: type[BaseModel], *args: Any, **kwargs: Any) -> Any:
            if _active is not None:
                _active["pydantic_json_decodes"] += 1
            return current_validate_json.__func__(cls, *args, **kwargs)

        tracked_validate_json._profile_0115 = True  # type: ignore[attr-defined]
        BaseModel.model_validate_json = classmethod(tracked_validate_json)

    for module in tuple(sys.modules.values()):
        namespace = getattr(module, "__dict__", None)
        if not isinstance(namespace, dict):
            continue
        for name, value in tuple(namespace.items()):
            if not (
                name.startswith("parse_")
                and name.endswith("_data_bytes")
                and callable(value)
                and not getattr(value, "_profile_0115", False)
            ):
                continue

            def make_wrapper(function: Any, parser_name: str) -> Any:
                def tracked_parser(*args: Any, **kwargs: Any) -> Any:
                    if _active is not None:
                        _active["domain_parsers"][parser_name] += 1
                    return function(*args, **kwargs)

                tracked_parser._profile_0115 = True
                return tracked_parser

            namespace[name] = make_wrapper(value, name)


async def _measure_request(app: Any, case: pipeline_profile.Scenario, root: Path) -> None:
    global _active
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://m0-profile.local",
            timeout=180,
        ) as client,
    ):
        _wrap_decoders()
        state: dict[str, Any] = {
            "root": root.resolve(),
            "repo_data": pipeline_profile.ROOT / "data",
            "repo_runtime": pipeline_profile.ROOT / ".runtime",
            "reads": [],
            "live_reads": [],
            "stdlib_json_loads": 0,
            "pydantic_json_decodes": 0,
            "domain_parsers": Counter(),
        }
        started = time.perf_counter_ns()
        _active = state
        try:
            response = await client.request(case.method, case.path, json=case.body)
        finally:
            _active = None
        elapsed = time.perf_counter_ns() - started
        error = pipeline_profile._check(case, response)
        root = state["root"]
        reads = state["reads"]
        live_reads = state["live_reads"]
        relative = [str(path.relative_to(root)) for path in reads]
        json_paths = sorted({path for path in relative if path.endswith(".json")})
        _requests.append(
            {
                "case": case.name,
                "duration_ns": elapsed,
                "status_code": response.status_code,
                "response_bytes": len(response.content),
                "response_sha256": hashlib.sha256(response.content).hexdigest(),
                "ok": error is None,
                "error": error,
                "isolated_data_read_open_count": len(reads),
                "live_data_read_open_count": len(live_reads),
                "live_data_paths_read": sorted({str(path) for path in live_reads}),
                "unique_data_paths_read": len(set(relative)),
                "unique_json_paths_read": len(json_paths),
                "json_paths_read": json_paths,
                "stdlib_json_loads": state["stdlib_json_loads"],
                "pydantic_json_decodes": state["pydantic_json_decodes"],
                "domain_data_parser_calls": dict(sorted(state["domain_parsers"].items())),
            }
        )


def run(hard_cache: Path, case_names: set[str]) -> dict[str, Any]:
    from dokodetector_backend.app import create_app

    cases = {case.name: case for case in pipeline_profile.scenarios()}
    unknown = case_names - cases.keys()
    if unknown:
        raise ValueError(f"unknown pipeline case names: {sorted(unknown)}")
    _requests.clear()
    with tempfile.TemporaryDirectory(prefix="doko-0115-io-profile-") as temp:
        parent = Path(temp)
        for name in sorted(case_names):
            root = parent / name
            root.mkdir()
            pipeline_profile._link_hard_snapshot(root, hard_cache)
            if name in {"calibration_draft_snapshot", "calibration_draft_invalid_lineage"}:
                pipeline_profile._prepare_current_calibration_draft_fixture(root)
            app = create_app(pipeline_profile._settings(root))
            if name in {
                "event_runs_exact",
                "event_result_exact",
                "event_selection_exact",
                "comparison_exact_runs",
            }:
                pipeline_profile._seed_event_result(
                    app, include_comparison=name == "comparison_exact_runs"
                )
            if name == "automated_run_exact":
                pipeline_profile._seed_automated_run(app)
            asyncio.run(_measure_request(app, cases[name], root))
    manifest_digest = hashlib.sha256(pipeline_profile.MANIFEST.read_bytes()).hexdigest()
    return {
        "schema_version": "0115-application-io-profile/v1",
        "source_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=pipeline_profile.ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "hard_manifest_sha256": manifest_digest,
        "counter_scope": {
            "read_opens": (
                "Python audit open events under the fixture root or live data/runtime roots "
                "during one HTTP request"
            ),
            "json_loads": (
                "stdlib json.loads calls during the request; this is not every native parser"
            ),
            "pydantic_json_decodes": "BaseModel.model_validate_json calls during the request",
            "domain_data_parser_calls": "parse_*_data_bytes functions loaded by the app",
            "setup_and_startup": "excluded; each case uses a fresh isolated app and fixture",
        },
        "cases": _requests,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hard-cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.hard_cache, set(args.cases or DEFAULT_CASES))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    failures = [row for row in result["cases"] if not row["ok"]]
    print(f"Wrote {len(result['cases'])} cases to {args.output}; failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.addaudithook(_audit)
    raise SystemExit(main())
