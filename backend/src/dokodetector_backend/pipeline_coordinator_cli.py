"""Run one frozen recording through the retained pipeline stage APIs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

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
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--state-dir", type=Path, default=Path(".runtime/pipeline-coordinators/runs")
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
        document = PipelineCoordinator(
            arguments.state_dir,
            HttpPipelineStageExecutor(arguments.api_url),
        ).run(arguments.recording_id, plan, coordinator_id=coordinator_id)
    except (OSError, ValueError, PipelineCoordinatorError) as error:
        print(f"Pipeline coordinator failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(document, indent=2, sort_keys=True))
    if document["status"] != "complete":
        raise SystemExit(1)


def _safe_id(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(part for part in normalized.split("-") if part)[:48]


if __name__ == "__main__":
    main()
