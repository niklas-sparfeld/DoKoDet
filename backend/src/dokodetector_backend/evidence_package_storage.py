"""Atomic streaming storage for shared evidence-package bundles."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Mapping
from uuid import UUID

from dokodetector_backend.repository_bundle_storage import StoredRepositoryFile
from dokodetector_backend.storage import COPY_CHUNK_BYTES, StorageLimitError


class EvidencePackageStorage:
    """Store accepted evidence packages below the repository intake root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def package_path(self, package_id: UUID | str) -> Path:
        """Return the canonical path for one validated package ID."""

        return self.root / str(UUID(str(package_id)))

    def start_package(self, package_id: UUID | str) -> TemporaryEvidencePackage:
        """Create a private package directory below the canonical intake root."""

        package_uuid = UUID(str(package_id))
        self.root.mkdir(parents=True, exist_ok=True)
        temporary_path = Path(tempfile.mkdtemp(prefix=".upload-", dir=self.root))
        return TemporaryEvidencePackage(self, package_uuid, temporary_path)

    def file_digests(self, package_id: UUID | str) -> dict[str, StoredRepositoryFile]:
        """Hash every regular file in one canonical package."""

        package_path = self.package_path(package_id)
        if not package_path.is_dir():
            raise FileNotFoundError(package_path)
        files: dict[str, StoredRepositoryFile] = {}
        for path in sorted(path for path in package_path.rglob("*") if path.is_file()):
            relative_path = path.relative_to(package_path).as_posix()
            files[relative_path] = _hash_file(path, relative_path)
        return files

    def remove_package(self, package_id: UUID | str) -> None:
        """Remove one package during explicit persistence compensation."""

        package_path = self.package_path(package_id)
        if package_path.exists():
            shutil.rmtree(package_path)


def calculate_bundle_fingerprint(files: Mapping[str, StoredRepositoryFile]) -> str:
    """Calculate a stable fingerprint for every canonical package member."""

    canonical = "\n".join(
        f"{relative_path}\0{files[relative_path].byte_length}\0{files[relative_path].sha256}"
        for relative_path in sorted(files)
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class TemporaryEvidencePackage:
    """Build one package and atomically rename it to its canonical directory."""

    def __init__(
        self,
        storage: EvidencePackageStorage,
        package_id: UUID,
        temporary_path: Path,
    ) -> None:
        self.storage = storage
        self.package_id = package_id
        self.temporary_path = temporary_path
        self._committed = False

    def __enter__(self) -> TemporaryEvidencePackage:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if not self._committed:
            self.abort()

    def write_part(
        self,
        relative_path: str,
        source: bytes | BinaryIO,
        *,
        max_bytes: int | None = None,
    ) -> StoredRepositoryFile:
        """Stream one package member into the private directory."""

        _validate_relative_path(relative_path)
        destination = self.temporary_path / PurePosixPath(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_stream = _source_stream(source)
        digest = hashlib.sha256()
        byte_length = 0
        try:
            with destination.open("xb") as handle:
                while chunk := source_stream.read(COPY_CHUNK_BYTES):
                    if not isinstance(chunk, bytes):
                        raise TypeError("evidence package sources must return bytes")
                    byte_length += len(chunk)
                    if max_bytes is not None and byte_length > max_bytes:
                        raise StorageLimitError(
                            "the evidence package member exceeds its size limit"
                        )
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return StoredRepositoryFile(relative_path, byte_length, digest.hexdigest())

    def read_part(self, relative_path: str) -> bytes:
        """Read a staged JSON member for contract validation."""

        _validate_relative_path(relative_path)
        return (self.temporary_path / PurePosixPath(relative_path)).read_bytes()

    def file_digests(self) -> dict[str, StoredRepositoryFile]:
        """Return exact digests for every staged member."""

        files: dict[str, StoredRepositoryFile] = {}
        for path in sorted(path for path in self.temporary_path.rglob("*") if path.is_file()):
            relative_path = path.relative_to(self.temporary_path).as_posix()
            files[relative_path] = _hash_file(path, relative_path)
        return files

    def commit(self) -> dict[str, StoredRepositoryFile]:
        """Atomically publish the private package directory."""

        final_path = self.storage.package_path(self.package_id)
        if final_path.exists():
            raise FileExistsError(final_path)
        files = self.file_digests()
        self.temporary_path.rename(final_path)
        self._committed = True
        return files

    def abort(self) -> None:
        """Remove the private package directory."""

        if self.temporary_path.exists():
            shutil.rmtree(self.temporary_path)


def _source_stream(source: bytes | BinaryIO) -> BinaryIO:
    if isinstance(source, bytes):
        from io import BytesIO

        return BytesIO(source)
    return source


def _validate_relative_path(relative_path: str) -> None:
    path = PurePosixPath(relative_path)
    if (
        not relative_path
        or "\\" in relative_path
        or path.is_absolute()
        or ".." in path.parts
        or path.name in {"", "."}
    ):
        raise ValueError("evidence package paths must be safe relative paths")


def _hash_file(path: Path, relative_path: str) -> StoredRepositoryFile:
    digest = hashlib.sha256()
    byte_length = 0
    with path.open("rb") as handle:
        while chunk := handle.read(COPY_CHUNK_BYTES):
            byte_length += len(chunk)
            digest.update(chunk)
    return StoredRepositoryFile(relative_path, byte_length, digest.hexdigest())


__all__ = [
    "EvidencePackageStorage",
    "TemporaryEvidencePackage",
    "calculate_bundle_fingerprint",
]
