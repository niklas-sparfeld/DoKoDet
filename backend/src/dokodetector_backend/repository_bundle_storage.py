"""Atomic streaming storage for shared repository-intake bundles."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from dokodetector_backend.storage import COPY_CHUNK_BYTES, StorageLimitError


@dataclass(frozen=True, slots=True)
class StoredRepositoryFile:
    """Size and digest metadata for one accepted bundle member."""

    relative_path: str
    byte_length: int
    sha256: str


class RepositoryBundleStorage:
    """Store complete repository bundles below the configured intake root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def bundle_path(self, recording_id: str) -> Path:
        """Return the canonical directory for one recording."""

        return self.root / recording_id

    def start_bundle(self, recording_id: str) -> TemporaryRepositoryBundle:
        """Create a private temporary bundle below the configured root."""

        self.root.mkdir(parents=True, exist_ok=True)
        temporary_path = Path(tempfile.mkdtemp(prefix=".upload-", dir=self.root))
        return TemporaryRepositoryBundle(self, recording_id, temporary_path)

    def file_digests(self, recording_id: str) -> dict[str, StoredRepositoryFile]:
        """Hash every regular file in one committed bundle."""

        bundle_path = self.bundle_path(recording_id)
        if not bundle_path.is_dir():
            raise FileNotFoundError(bundle_path)
        files: dict[str, StoredRepositoryFile] = {}
        for path in sorted(path for path in bundle_path.rglob("*") if path.is_file()):
            relative_path = path.relative_to(bundle_path).as_posix()
            files[relative_path] = _hash_file(path, relative_path)
        return files

    def remove_bundle(self, recording_id: str) -> None:
        """Remove a canonical bundle during explicit recovery."""

        path = self.bundle_path(recording_id)
        if path.exists():
            shutil.rmtree(path)


class TemporaryRepositoryBundle:
    """Build one bundle and atomically rename it to its canonical directory."""

    def __init__(
        self,
        storage: RepositoryBundleStorage,
        recording_id: str,
        temporary_path: Path,
    ) -> None:
        self.storage = storage
        self.recording_id = recording_id
        self.temporary_path = temporary_path
        self._committed = False

    def __enter__(self) -> TemporaryRepositoryBundle:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if not self._committed:
            self.abort()

    def write_part(
        self,
        relative_path: str,
        source: BinaryIO,
        *,
        max_bytes: int | None = None,
    ) -> StoredRepositoryFile:
        """Stream one multipart part into the temporary bundle."""

        _validate_relative_path(relative_path)
        destination = self.temporary_path / PurePosixPath(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        byte_length = 0
        try:
            with destination.open("xb") as handle:
                while chunk := source.read(COPY_CHUNK_BYTES):
                    if not isinstance(chunk, bytes):
                        raise TypeError("repository upload sources must return bytes")
                    byte_length += len(chunk)
                    if max_bytes is not None and byte_length > max_bytes:
                        raise StorageLimitError("the repository upload part exceeds its size limit")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return StoredRepositoryFile(relative_path, byte_length, digest.hexdigest())

    def read_part(self, relative_path: str) -> bytes:
        """Read a staged JSON part for contract validation."""

        _validate_relative_path(relative_path)
        return (self.temporary_path / PurePosixPath(relative_path)).read_bytes()

    def file_digests(self) -> dict[str, StoredRepositoryFile]:
        """Return staged file digests for exact bundle validation."""

        files: dict[str, StoredRepositoryFile] = {}
        for path in sorted(path for path in self.temporary_path.rglob("*") if path.is_file()):
            relative_path = path.relative_to(self.temporary_path).as_posix()
            files[relative_path] = _hash_file(path, relative_path)
        return files

    def commit(self) -> dict[str, StoredRepositoryFile]:
        """Atomically publish the complete temporary bundle."""

        final_path = self.storage.bundle_path(self.recording_id)
        if final_path.exists():
            raise FileExistsError(final_path)
        files = self.file_digests()
        self.temporary_path.rename(final_path)
        self._committed = True
        return files

    def abort(self) -> None:
        """Remove the uncommitted temporary bundle."""

        if self.temporary_path.exists():
            shutil.rmtree(self.temporary_path)


def bundle_fingerprint(files: dict[str, StoredRepositoryFile]) -> str:
    """Return a deterministic identity for all committed bundle members."""

    digest = hashlib.sha256()
    for relative_path in sorted(files):
        file = files[relative_path]
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(file.byte_length).encode("ascii"))
        digest.update(b"\0")
        digest.update(file.sha256.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_relative_path(relative_path: str) -> None:
    path = PurePosixPath(relative_path)
    if not relative_path or path.is_absolute() or ".." in path.parts or path.name in {"", "."}:
        raise ValueError("repository bundle paths must be safe relative paths")


def _hash_file(path: Path, relative_path: str) -> StoredRepositoryFile:
    digest = hashlib.sha256()
    byte_length = 0
    with path.open("rb") as handle:
        while chunk := handle.read(COPY_CHUNK_BYTES):
            byte_length += len(chunk)
            digest.update(chunk)
    return StoredRepositoryFile(relative_path, byte_length, digest.hexdigest())


__all__ = [
    "RepositoryBundleStorage",
    "StoredRepositoryFile",
    "TemporaryRepositoryBundle",
    "bundle_fingerprint",
]
