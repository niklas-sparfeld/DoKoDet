"""Bounded atomic storage for raw videos that need operator metadata."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from dokodetector_backend.storage import COPY_CHUNK_BYTES, StorageLimitError

SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class StoredPendingVideo:
    """Size and digest metadata for one staged raw video."""

    filename: str
    byte_length: int
    sha256: str


class PendingVideoStorage:
    """Store one raw video and receipt below the pending-video root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def upload_path(self, upload_id: str) -> Path:
        """Return the canonical directory for one safe upload identifier."""

        _validate_identifier(upload_id)
        return self.root / upload_id

    def start_upload(self, upload_id: str) -> TemporaryPendingVideo:
        """Create a private temporary upload directory below the pending root."""

        self.root.mkdir(parents=True, exist_ok=True)
        temporary_path = Path(tempfile.mkdtemp(prefix=".upload-", dir=self.root))
        return TemporaryPendingVideo(self, upload_id, temporary_path)

    def receipt_path(self, upload_id: str) -> Path:
        """Return the receipt path for one pending upload."""

        return self.upload_path(upload_id) / "manifest.json"

    def read_receipt(self, upload_id: str) -> bytes:
        """Read one durable pending-upload receipt."""

        return self.receipt_path(upload_id).read_bytes()


class TemporaryPendingVideo:
    """Build one pending upload and atomically publish its directory."""

    def __init__(self, storage: PendingVideoStorage, upload_id: str, temporary_path: Path) -> None:
        self.storage = storage
        self.upload_id = upload_id
        self.temporary_path = temporary_path
        self._committed = False

    def __enter__(self) -> TemporaryPendingVideo:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if not self._committed:
            self.abort()

    def write_video(
        self, filename: str, source: BinaryIO, *, max_bytes: int | None = None
    ) -> StoredPendingVideo:
        """Stream one raw video into the private upload directory."""

        _validate_filename(filename)
        destination = self.temporary_path / filename
        digest = hashlib.sha256()
        byte_length = 0
        try:
            with destination.open("xb") as handle:
                while chunk := source.read(COPY_CHUNK_BYTES):
                    if not isinstance(chunk, bytes):
                        raise TypeError("pending video sources must return bytes")
                    byte_length += len(chunk)
                    if max_bytes is not None and byte_length > max_bytes:
                        raise StorageLimitError("the pending video exceeds its size limit")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return StoredPendingVideo(filename, byte_length, digest.hexdigest())

    def write_receipt(self, receipt: bytes) -> None:
        """Write the validated pending-video receipt into the private directory."""

        if not isinstance(receipt, bytes) or not receipt:
            raise ValueError("the pending video receipt must contain bytes")
        destination = self.temporary_path / "manifest.json"
        with destination.open("xb") as handle:
            handle.write(receipt)
            handle.flush()
            os.fsync(handle.fileno())

    def commit(self) -> Path:
        """Atomically publish the complete pending upload directory."""

        final_path = self.storage.upload_path(self.upload_id)
        if final_path.exists():
            raise FileExistsError(final_path)
        self.temporary_path.rename(final_path)
        self._committed = True
        return final_path

    def abort(self) -> None:
        """Remove the private upload directory."""

        if self.temporary_path.exists():
            shutil.rmtree(self.temporary_path)


def _validate_identifier(value: str) -> None:
    if SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ValueError("pending video upload IDs must be safe identifiers")


def _validate_filename(value: str) -> None:
    if SAFE_FILENAME.fullmatch(value) is None or Path(value).name != value:
        raise ValueError("pending video filenames must be safe filenames")


__all__ = ["PendingVideoStorage", "StoredPendingVideo", "TemporaryPendingVideo"]
