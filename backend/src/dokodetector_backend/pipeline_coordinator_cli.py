"""Run one frozen recording through the retained pipeline stage APIs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from uuid import uuid4

from dokodetector_backend.pipeline_coordinator import (
    HttpPipelineStageExecutor,
    PipelineCoordinator,
    PipelineCoordinatorError,
    frozen_pilot_stage_plan,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the frozen 0090 retained pipeline stages for one recording."
    )
    parser.add_argument("recording_id")
    parser.add_argument("--coordinator-id", help="Use a saved coordinator run ID.")
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--state-dir", type=Path, default=Path(".runtime/pipeline-coordinators/runs")
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--status", action="store_true", help="Read the saved run status.")
    actions.add_argument("--cancel", action="store_true", help="Cancel a running coordinator.")
    actions.add_argument(
        "--rerun", action="store_true", help="Start a fresh run with the same requests."
    )
    arguments = parser.parse_args()

    try:
        request_map = json.loads(arguments.requests.read_text(encoding="utf-8"))
        if not isinstance(request_map, dict):
            raise ValueError("The requests file must contain an object keyed by stage name.")
        plan = frozen_pilot_stage_plan(request_map)
        request_digest = hashlib.sha256(
            json.dumps(request_map, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:12]
        coordinator_id = f"0090-{_safe_id(arguments.recording_id)}-{request_digest}"
        if arguments.rerun:
            coordinator_id += f"-rerun-{uuid4().hex[:8]}"
        if arguments.coordinator_id:
            coordinator_id = arguments.coordinator_id
        executor = (
            None
            if arguments.status or arguments.cancel
            else HttpPipelineStageExecutor(arguments.api_url)
        )
        coordinator = PipelineCoordinator(arguments.state_dir, executor)
        if arguments.status:
            document = coordinator.read_status(coordinator_id)
        elif arguments.cancel:
            coordinator.request_cancel(coordinator_id)
            document = {"coordinator_id": coordinator_id, "status": "cancellation_requested"}
        else:
            document = coordinator.run(arguments.recording_id, plan, coordinator_id=coordinator_id)
    except (OSError, ValueError, PipelineCoordinatorError) as error:
        print(f"Pipeline coordinator failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(document, indent=2, sort_keys=True))
    if document["status"] not in {"complete", "cancellation_requested"}:
        raise SystemExit(1)


def _safe_id(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(part for part in normalized.split("-") if part)[:48]


if __name__ == "__main__":
    main()
