"""Real-process browser benchmark app with deterministic local event work."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from test_visible_card_pipeline_api import _FrameResolver

from dokodetector_backend.app import create_app as create_backend_app
from dokodetector_backend.poc_analyzer import create_local_poc_analyzer


class DeterministicEventProvider:
    """Produce small reproducible event results for browser job workflows."""

    def infer(
        self,
        video_path: Path,
        *,
        request: Any,
        progress_callback: Any | None = None,
    ) -> dict[str, object]:
        del video_path, request
        delay_ms = max(0, int(os.environ.get("UI_PERF_JOB_DELAY_MS", "0")))
        if delay_ms:
            time.sleep(delay_ms / 1000)
        if progress_callback is not None:
            progress_callback(1, 2)
            progress_callback(2, 2)
        return {
            "events": [
                {"time_s": 0.1, "probability": 0.9},
                {"time_s": 0.3, "probability": 0.8},
                {"time_s": 0.4, "probability": 0.7},
                {"time_s": 0.5, "probability": 0.6, "event_type": "trick_taken"},
                {"time_s": 0.6, "probability": 0.5},
            ]
        }


def create_app():
    """Create the production application with explicit local benchmark providers."""

    return create_backend_app(
        analyzer=create_local_poc_analyzer(),
        event_provider=DeterministicEventProvider(),
        visible_card_frame_resolver=_FrameResolver(),
    )
