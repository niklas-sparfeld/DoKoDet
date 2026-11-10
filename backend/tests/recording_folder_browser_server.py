"""Disposable backend for the recording folder browser proof."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.poc_analyzer import create_local_poc_analyzer
from dokodetector_backend.recording_folder_store import RecordingFolderStore


def main() -> None:
    repository = Path(__file__).parents[2]
    fixture = repository / "fixtures/repository-bundle/v1/both"
    with TemporaryDirectory(prefix="recording-folder-browser-") as directory:
        data_root = Path(directory) / "data" / "recordings"
        RecordingFolderStore(data_root).publish_bundle(fixture, recording_id="recording-both")
        settings = Settings(
            _env_file=None,
            repository_root=repository,
            recordings_root=data_root,
            evidence_root=Path(directory) / "runtime",
            operations_root=Path(directory) / "operations",
            repository_intake_root=Path(directory) / "transport",
            evidence_package_intake_root=Path(directory) / "packages",
            pending_video_root=Path(directory) / "incoming",
            frontend_dist=repository / "web" / "dist",
        )
        app = create_app(settings, analyzer=create_local_poc_analyzer())

        def forbidden(*_args, **_kwargs):
            raise AssertionError("the retired recording catalog was called")

        app.state.recording_bundle_store.list_metadata = forbidden
        uvicorn.run(app, host="127.0.0.1", port=8767, log_level="warning")


if __name__ == "__main__":
    main()
