"""Atomic streaming filesystem storage for training-recording bundles."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from dokodetector_backend.storage import COPY_CHUNK_BYTES, SAFE_PART_NAME, StorageLimitError


@dataclass(frozen=True, slots=True)
class StoredRecordingFiles:
    """The immutable files committed for one recording."""

    manifest: StoredFile
    video: StoredFile
    predictions: StoredFile


@dataclass(frozen=True, slots=True)
class StoredFile:
    """Size and digest metadata for one stored file."""

    relative_path: str
    byte_length: int
    sha256: str


class TrainingRecordingStorage:
    """Store accepted recordings below a local intake root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.training_recordings_root = self.root / "training-recordings"

    def recording_path(self, recording_id: str) -> Path:
        """Return the final directory for one validated recording ID."""

        return self.training_recordings_root / recording_id

    def start_recording(self, recording_id: str) -> TemporaryTrainingRecording:
        """Create a temporary recording directory below the intake root."""

        final_path = self.recording_path(recording_id)
        if final_path.exists():
            raise FileExistsError("The recording directory already exists.")

        self.training_recordings_root.mkdir(parents=True, exist_ok=True)
        temporary_path = Path(
            tempfile.mkdtemp(prefix=".upload-", dir=self.training_recordings_root)
        )
        (temporary_path / "videos").mkdir()
        (temporary_path / "predictions").mkdir()
        return TemporaryTrainingRecording(self, recording_id, temporary_path)

    def write_derived(
        self,
        recording_id: str,
        *,
        dataset_record: bytes,
        candidate_queue: bytes | None,
    ) -> tuple[StoredFile, StoredFile | None]:
        """Write derived artifacts atomically after the immutable bundle is committed."""

        recording_path = self.recording_path(recording_id)
        intake_path = recording_path / "intake"
        intake_path.mkdir()
        dataset_file = self._write_derived_file(
            intake_path,
            "dataset-record.yaml",
            dataset_record,
            recording_id,
        )
        queue_file = None
        if candidate_queue is not None:
            queue_file = self._write_derived_file(
                intake_path,
                "candidate-review-queue.json",
                candidate_queue,
                recording_id,
            )
        return dataset_file, queue_file

    def remove_recording(self, recording_id: str) -> None:
        """Remove one recording directory during persistence compensation."""

        path = self.recording_path(recording_id)
        if path.exists():
            shutil.rmtree(path)

    def _write_derived_file(
        self,
        intake_path: Path,
        name: str,
        value: bytes,
        recording_id: str,
    ) -> StoredFile:
        temporary_path = intake_path / f".{name}.{recording_id}.tmp"
        final_path = intake_path / name
        digest = hashlib.sha256(value).hexdigest()
        try:
            with temporary_path.open("xb") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, final_path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
        return StoredFile(
            relative_path=f"training-recordings/{recording_id}/intake/{name}",
            byte_length=len(value),
            sha256=digest,
        )


class TemporaryTrainingRecording:
    """Build one recording and atomically rename it to final storage."""

    def __init__(
        self,
        storage: TrainingRecordingStorage,
        recording_id: str,
        temporary_path: Path,
    ) -> None:
        self.storage = storage
        self.recording_id = recording_id
        self.temporary_path = temporary_path
        self._manifest: StoredFile | None = None
        self._video: StoredFile | None = None
        self._predictions: StoredFile | None = None
        self._committed = False

    def __enter__(self) -> TemporaryTrainingRecording:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if not self._committed:
            self.abort()

    def write_manifest(self, source: bytes) -> StoredFile:
        """Write the original manifest bytes to the temporary bundle."""

        if self._manifest is not None:
            raise FileExistsError("The recording manifest was already written.")
        self._manifest = self._copy_bytes("manifest.json", source)
        return self._manifest

    def write_predictions(self, name: str, source: bytes) -> StoredFile:
        """Write the original prediction bytes to the temporary bundle."""

        if self._predictions is not None:
            raise FileExistsError("The recording predictions were already written.")
        if not SAFE_PART_NAME.fullmatch(name) or not name.endswith(".json"):
            raise ValueError("The recording predictions name is not safe.")
        self._predictions = self._copy_bytes(f"predictions/{name}", source)
        return self._predictions

    def write_video(
        self,
        name: str,
        source: BinaryIO,
        *,
        max_bytes: int | None = None,
    ) -> StoredFile:
        """Stream the source video into the temporary bundle while hashing it."""

        if self._video is not None:
            raise FileExistsError("The recording video was already written.")
        if not SAFE_PART_NAME.fullmatch(name) or not name.endswith(".mov"):
            raise ValueError("The recording video name is not safe.")
        self._video = self._copy(
            f"videos/{name}",
            source,
            max_bytes=max_bytes,
        )
        return self._video

    def commit(self) -> StoredRecordingFiles:
        """Rename the complete temporary directory to its final path."""

        if self._manifest is None or self._video is None or self._predictions is None:
            raise ValueError("Manifest, video, and predictions must be written before commit.")
        final_path = self.storage.recording_path(self.recording_id)
        if final_path.exists():
            raise FileExistsError("The recording directory already exists.")
        self.temporary_path.rename(final_path)
        self._committed = True
        return StoredRecordingFiles(
            manifest=_with_final_path(self._manifest, self.recording_id),
            video=_with_final_path(self._video, self.recording_id),
            predictions=_with_final_path(self._predictions, self.recording_id),
        )

    def abort(self) -> None:
        """Remove an uncommitted temporary recording directory."""

        if self.temporary_path.exists():
            shutil.rmtree(self.temporary_path)

    def _copy_bytes(self, relative_path: str, source: bytes) -> StoredFile:
        if not isinstance(source, bytes):
            raise TypeError("Recording sources must be bytes.")
        return self._copy(relative_path, _BytesReader(source), max_bytes=None)

    def _copy(
        self,
        relative_path: str,
        source: BinaryIO,
        *,
        max_bytes: int | None,
    ) -> StoredFile:
        destination_path = self.temporary_path / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        byte_length = 0
        try:
            with destination_path.open("xb") as destination:
                while chunk := source.read(COPY_CHUNK_BYTES):
                    if not isinstance(chunk, bytes):
                        raise TypeError("Recording sources must return bytes.")
                    byte_length += len(chunk)
                    if max_bytes is not None and byte_length > max_bytes:
                        raise StorageLimitError("The recording file exceeds its size limit.")
                    digest.update(chunk)
                    destination.write(chunk)
        except BaseException:
            destination_path.unlink(missing_ok=True)
            raise
        return StoredFile(
            relative_path=relative_path,
            byte_length=byte_length,
            sha256=digest.hexdigest(),
        )


class _BytesReader:
    """Minimal binary reader for the common byte-backed JSON parts."""

    def __init__(self, value: bytes) -> None:
        self.value = value
        self.offset = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.value) - self.offset
        start = self.offset
        self.offset = min(len(self.value), self.offset + size)
        return self.value[start : self.offset]


def _with_final_path(file: StoredFile, recording_id: str) -> StoredFile:
    return StoredFile(
        relative_path=f"training-recordings/{recording_id}/{file.relative_path}",
        byte_length=file.byte_length,
        sha256=file.sha256,
    )


__all__ = [
    "StoredFile",
    "StoredRecordingFiles",
    "TemporaryTrainingRecording",
    "TrainingRecordingStorage",
]
