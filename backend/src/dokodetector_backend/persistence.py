"""Coordinate atomic evidence files and SQLite metadata."""

from __future__ import annotations

from dataclasses import replace
from typing import BinaryIO

from dokodetector_backend.repository import EvidenceRepository, StoredPackage
from dokodetector_backend.storage import EvidenceStorage


class EvidencePackagePersister:
    """Store files first, then commit their metadata in SQLite."""

    def __init__(self, repository: EvidenceRepository, storage: EvidenceStorage) -> None:
        self.repository = repository
        self.storage = storage

    def persist(
        self,
        package: StoredPackage,
        manifest_source: bytes | BinaryIO,
        frame_sources: dict[str, bytes | BinaryIO],
        *,
        max_manifest_bytes: int | None = None,
        max_frame_bytes: int | None = None,
    ) -> StoredPackage:
        """Persist one package and clean up files if the database insert fails."""

        committed = False
        with self.storage.start_package(package.package_id) as upload:
            upload.write_manifest(manifest_source, max_bytes=max_manifest_bytes)
            stored_frames = {
                frame.part_name: upload.write_frame(
                    frame.part_name,
                    frame_sources[frame.part_name],
                    max_bytes=max_frame_bytes,
                )
                for frame in package.frames
            }
            upload.commit()
            committed = True

        package_with_paths = replace(
            package,
            frames=tuple(
                replace(
                    frame,
                    relative_path=stored_frames[frame.part_name].relative_path,
                )
                for frame in package.frames
            ),
        )
        try:
            return self.repository.insert_package(package_with_paths)
        except BaseException:
            if committed:
                self.storage.remove_package(package.package_id)
            raise


__all__ = ["EvidencePackagePersister"]
