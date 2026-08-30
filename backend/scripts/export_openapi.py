"""Write the test-configured FastAPI OpenAPI document for frontend generation."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.poc_analyzer import create_local_poc_analyzer


def main() -> None:
    """Create the application with isolated test storage and write its OpenAPI document."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    repository_root = Path(__file__).resolve().parents[2]
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dokodetector-openapi-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        settings = Settings(
            _env_file=None,
            repository_root=repository_root,
            database_url=f"sqlite:///{temporary_root / 'backend.sqlite'}",
            evidence_root=temporary_root / "runtime",
            repository_intake_root=temporary_root / "recordings",
            evidence_package_intake_root=temporary_root / "evidence-packages",
            pending_video_root=temporary_root / "pending-videos",
            bonjour_enabled=False,
        )
        app = create_app(settings, analyzer=create_local_poc_analyzer())
        document = json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True)
        arguments.output.write_text(f"{document}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
