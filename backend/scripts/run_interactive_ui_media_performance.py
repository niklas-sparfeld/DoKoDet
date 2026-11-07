#!/usr/bin/env python3
"""Run named real-backend media cases and retain preliminary samples as JSON."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "backend/tests"
sys.path.insert(0, str(TESTS))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import pytest

    result = pytest.main(["-q", str(TESTS / "test_interactive_ui_media_performance.py")])
    if result != pytest.ExitCode.OK:
        return int(result)
    test_module = sys.modules.get("test_interactive_ui_media_performance")
    samples = getattr(test_module, "SAMPLES", None)
    if not samples:
        raise RuntimeError("The media tests completed without retaining timing samples.")
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "schema_version": "interactive-ui-media-samples/v1",
                "kind": "preliminary_real_backend_media_samples",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "metadata": {
                    "commit": subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        cwd=ROOT,
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip(),
                    "platform": platform.platform(),
                    "python": sys.version.split()[0],
                    "transport": "FastAPI TestClient; real app and storage handlers",
                    "thumbnail_generation": "deterministic renderer stub; route/cache path real",
                    "cache_policy": "cold then warm derived media; new identity revision; restart",
                },
                "samples": samples,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"retained {len(samples)} samples at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
