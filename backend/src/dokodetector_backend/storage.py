"""Atomic local filesystem storage for evidence packages."""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

SAFE_PART_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
COPY_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class StoredFile:
    """Digest and relative path for one stored file."""

    relative_path: str
    byte_length: int
    sha256: str


@dataclass(frozen=True, slots=True)
class StoredEvidencePackage:
    """Files written for one committed evidence package."""

    package_id: UUID
    manifest: StoredFile
    frames: tuple[StoredFile, ...]


class EvidenceStorage:
    """Store package files below one local evidence root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.evidence_root = self.root / "evidence"

    def start_package(self, package_id: UUID | str) -> TemporaryEvidencePackage:
        """Create a temporary package directory below the final root."""

        package_uuid = UUID(str(package_id))
        final_path = self.package_path(package_uuid)
        if final_path.exists():
            raise FileExistsError("The package directory already exists.")

        self.evidence_root.mkdir(parents=True, exist_ok=True)
        temporary_path = Path(tempfile.mkdtemp(prefix=".upload-", dir=self.evidence_root))
        (temporary_path / "frames").mkdir()
        return TemporaryEvidencePackage(self, package_uuid, temporary_path)

    def package_path(self, package_id: UUID | str) -> Path:
        """Return the final path for one validated package ID."""

        return self.evidence_root / str(UUID(str(package_id)))

    def remove_package(self, package_id: UUID | str) -> None:
        """Remove a package directory after a failed database insert."""

        package_path = self.package_path(package_id)
        if package_path.exists():
            shutil.rmtree(package_path)


class TemporaryEvidencePackage:
    """Build one package and atomically rename it into final storage."""

    def __init__(self, storage: EvidenceStorage, package_id: UUID, temporary_path: Path) -> None:
        self.storage = storage
        self.package_id = package_id
        self.temporary_path = temporary_path
        self._manifest: StoredFile | None = None
        self._frames: dict[str, StoredFile] = {}
        self._committed = False

    def __enter__(self) -> TemporaryEvidencePackage:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if not self._committed:
            self.abort()

    def write_manifest(
        self, source: bytes | BinaryIO, *, max_bytes: int | None = None
    ) -> StoredFile:
        """Copy the original manifest bytes into the temporary package."""

        if self._manifest is not None:
            raise FileExistsError("The manifest was already written.")
        self._manifest = self._copy(
            "manifest.json",
            source,
            max_bytes=max_bytes,
        )
        return _with_final_path(self._manifest, self.package_id)

    def write_frame(
        self,
        part_name: str,
        source: bytes | BinaryIO,
        *,
        max_bytes: int | None = None,
    ) -> StoredFile:
        """Copy one frame into the temporary package."""

        if not SAFE_PART_NAME.fullmatch(part_name) or len(part_name) > 64:
            raise ValueError("Frame part names must use a safe part name.")
        if part_name in self._frames:
            raise FileExistsError("The frame part was already written.")

        stored = self._copy(
            f"frames/{part_name}.jpg",
            source,
            max_bytes=max_bytes,
        )
        self._frames[part_name] = stored
        return _with_final_path(stored, self.package_id)

    def commit(self) -> StoredEvidencePackage:
        """Rename the complete temporary directory to its final path."""

        if self._manifest is None:
            raise ValueError("The manifest must be written before commit.")
        final_path = self.storage.package_path(self.package_id)
        if final_path.exists():
            raise FileExistsError("The package directory already exists.")

        self.temporary_path.rename(final_path)
        self._committed = True
        return StoredEvidencePackage(
            package_id=self.package_id,
            manifest=_with_final_path(self._manifest, self.package_id),
            frames=tuple(
                _with_final_path(self._frames[part_name], self.package_id)
                for part_name in self._frames
            ),
        )

    def abort(self) -> None:
        """Remove an uncommitted temporary directory."""

        if self.temporary_path.exists():
            shutil.rmtree(self.temporary_path)

    def _copy(
        self,
        relative_temporary_path: str,
        source: bytes | BinaryIO,
        *,
        max_bytes: int | None,
    ) -> StoredFile:
        source_stream: BinaryIO = BytesIO(source) if isinstance(source, bytes) else source
        temporary_file_path = self.temporary_path / relative_temporary_path
        temporary_file_path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        byte_length = 0
        try:
            with temporary_file_path.open("xb") as destination:
                while chunk := source_stream.read(COPY_CHUNK_BYTES):
                    if not isinstance(chunk, bytes):
                        raise TypeError("Evidence sources must return bytes.")
                    byte_length += len(chunk)
                    if max_bytes is not None and byte_length > max_bytes:
                        raise StorageLimitError("The evidence file exceeds its size limit.")
                    digest.update(chunk)
                    destination.write(chunk)
        except BaseException:
            temporary_file_path.unlink(missing_ok=True)
            raise

        return StoredFile(
            relative_path=relative_temporary_path,
            byte_length=byte_length,
            sha256=digest.hexdigest(),
        )


class StorageLimitError(ValueError):
    """A file exceeded its configured storage limit."""


def _with_final_path(stored_file: StoredFile, package_id: UUID) -> StoredFile:
    return StoredFile(
        relative_path=f"evidence/{package_id}/{stored_file.relative_path}",
        byte_length=stored_file.byte_length,
        sha256=stored_file.sha256,
    )


__all__ = [
    "EvidenceStorage",
    "SAFE_PART_NAME",
    "StorageLimitError",
    "StoredEvidencePackage",
    "StoredFile",
    "TemporaryEvidencePackage",
]
