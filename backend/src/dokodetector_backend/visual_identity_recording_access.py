"""Validate accepted recording identity and resolve its video path."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from doko_operations.pipeline_data import RecordingVideoSource

from dokodetector_backend.config import Settings
from dokodetector_backend.pipeline_storage import PipelineNotFound
from dokodetector_backend.recording_bundle_store import RecordingBundleStore
from dokodetector_backend.recording_folder_store import RecordingFolderStore
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage
from dokodetector_backend.visual_identity_pipeline_errors import VisualIdentityPipelineInputError


def _file_identity(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            length += len(chunk)
            digest.update(chunk)
    return length, digest.hexdigest()


class VisualIdentityRecordingAccess:
    """Resolve and verify the source video accepted for one recording."""

    def __init__(
        self,
        settings: Settings,
        recording_store: RecordingBundleStore,
        repository_storage: RepositoryBundleStorage,
        recording_folder_store: RecordingFolderStore | None = None,
    ) -> None:
        self.settings = settings
        self.recording_store = recording_store
        self.repository_storage = repository_storage
        self.recording_folder_store = recording_folder_store

    def accepted_source(self, recording_id: str) -> tuple[Any, RecordingVideoSource]:
        folder_recording = (
            None
            if self.recording_folder_store is None
            else self.recording_folder_store.get(recording_id)
        )
        bundle = None if folder_recording is not None else self.recording_store.get(recording_id)
        if folder_recording is None and bundle is None:
            raise PipelineNotFound(f"The recording was not found: {recording_id}")
        video_path = self.video_path(recording_id)
        if not video_path.is_file():
            raise VisualIdentityPipelineInputError("The accepted recording video is unavailable.")
        actual_length, actual_digest = _file_identity(video_path)
        expected_length = (
            folder_recording.media["byte_length"]
            if folder_recording is not None
            else bundle.video_byte_length
        )
        expected_digest = (
            folder_recording.media["sha256"]
            if folder_recording is not None
            else bundle.source_sha256
        )
        if actual_length != expected_length or actual_digest != expected_digest:
            raise VisualIdentityPipelineInputError(
                "The accepted recording video does not match its manifest."
            )
        try:
            from dokodetector_backend.video_probe import probe_video_path_metadata

            probe = probe_video_path_metadata(video_path)
        except Exception as error:
            raise VisualIdentityPipelineInputError(
                "The accepted recording video could not be probed."
            ) from error
        try:
            path_root = getattr(self.settings, "storage_root", None)
            path_root = path_root or self.settings.repository_root
            relative_path = video_path.resolve().relative_to(path_root.resolve()).as_posix()
        except ValueError as error:
            if folder_recording is None:
                raise VisualIdentityPipelineInputError(
                    "The accepted recording video is outside the repository root."
                ) from error
            relative_path = (
                Path("data/recordings") / recording_id / folder_recording.media["relative_path"]
            ).as_posix()
        return bundle, RecordingVideoSource(
            recording_id=recording_id,
            relative_path=relative_path,
            video_sha256=expected_digest,
            byte_length=actual_length,
            duration_us=probe.duration_ms * 1000,
        )

    def video_path(self, recording_id: str) -> Path:
        folder_recording = (
            None
            if self.recording_folder_store is None
            else self.recording_folder_store.get(recording_id)
        )
        if folder_recording is not None:
            return (
                self.recording_folder_store.recording_path(recording_id)
                / folder_recording.media["relative_path"]
            )
        manifest = self.repository_storage.bundle_path(recording_id) / "manifest.json"
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
            relative_path = value["files"]["video"]["relative_path"]
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise VisualIdentityPipelineInputError(
                "The accepted recording manifest is invalid."
            ) from error
        path = self.repository_storage.bundle_path(recording_id) / str(relative_path)
        try:
            path.resolve().relative_to(self.repository_storage.bundle_path(recording_id).resolve())
        except ValueError as error:
            raise VisualIdentityPipelineInputError(
                "The accepted recording video path is invalid."
            ) from error
        return path
