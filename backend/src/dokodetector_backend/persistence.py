"""Coordinate atomic evidence files and SQLite metadata."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, BinaryIO

from dokodetector_backend.repository import (
    EvidenceRepository,
    StoredPackage,
    StoredVisionResult,
    VisionResultInsert,
)
from dokodetector_backend.storage import EvidenceStorage

if TYPE_CHECKING:
    from vision_detector import VisionDetectionResult


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
        video_source: bytes | BinaryIO | None = None,
        video_part_name: str | None = None,
        *,
        max_manifest_bytes: int | None = None,
        max_frame_bytes: int | None = None,
        max_video_bytes: int | None = None,
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
            if video_source is not None:
                if video_part_name is None:
                    raise ValueError("A video part name is required for video bytes.")
                upload.write_video(
                    video_part_name,
                    video_source,
                    max_bytes=max_video_bytes,
                )
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


class VisionResultPersister:
    """Store canonical vision result bytes and database metadata together."""

    def __init__(self, repository: EvidenceRepository, storage: EvidenceStorage) -> None:
        self.repository = repository
        self.storage = storage

    def persist(self, result: VisionDetectionResult, result_bytes: bytes) -> StoredVisionResult:
        """Stage the result, insert metadata, and remove staged files on failure."""

        relative_path = f"vision-results/{result.result_id}/result.json"
        database_insert: VisionResultInsert | None = None
        with self.storage.start_vision_result(result.result_id) as staged:
            staged.write_result(result_bytes)
            database_insert = self.repository.insert_vision_result(
                result,
                result_bytes,
                relative_path,
            )
            if not database_insert.created:
                return database_insert.result
            try:
                staged.commit()
            except BaseException:
                self.repository.delete_vision_result(
                    result.result_id,
                    result_sha256=database_insert.result.result_sha256,
                )
                raise
        return database_insert.result


__all__ = ["EvidencePackagePersister", "VisionResultPersister"]
