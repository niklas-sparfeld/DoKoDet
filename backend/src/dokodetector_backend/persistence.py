"""Coordinate atomic evidence files and SQLite metadata."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, BinaryIO

from dokodetector_backend.evidence_package_storage import (
    EvidencePackageStorage,
    calculate_bundle_fingerprint,
)
from dokodetector_backend.repository import (
    EvidenceRepository,
    StoredPackage,
    StoredTableObservation,
    TableObservationInsert,
)
from dokodetector_backend.storage import EvidenceStorage

if TYPE_CHECKING:
    from table_evidence_analyzer import TableObservation


class EvidencePackagePersister:
    """Store files first, then commit their metadata in SQLite."""

    def __init__(self, repository: EvidenceRepository, storage: EvidencePackageStorage) -> None:
        self.repository = repository
        self.storage = storage

    def persist(
        self,
        package: StoredPackage,
        evidence_manifest_source: bytes | BinaryIO,
        package_record_source: bytes | BinaryIO,
        task_enrollment_source: bytes | BinaryIO,
        lineage_source: bytes | BinaryIO,
        bundle_manifest_source: bytes | BinaryIO,
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
            upload.write_part(
                "manifest.json",
                bundle_manifest_source,
                max_bytes=max_manifest_bytes,
            )
            upload.write_part(
                "evidence-manifest.json",
                evidence_manifest_source,
                max_bytes=max_manifest_bytes,
            )
            upload.write_part(
                "package-record.json",
                package_record_source,
                max_bytes=max_manifest_bytes,
            )
            upload.write_part(
                "initial-task-enrollment.json",
                task_enrollment_source,
                max_bytes=max_manifest_bytes,
            )
            upload.write_part("lineage.json", lineage_source, max_bytes=max_manifest_bytes)
            stored_frames = {
                frame.part_name: upload.write_part(
                    f"frames/{frame.part_name}.jpg",
                    frame_sources[frame.part_name],
                    max_bytes=max_frame_bytes,
                )
                for frame in package.frames
            }
            if video_source is not None:
                if video_part_name is None:
                    raise ValueError("A video part name is required for video bytes.")
                upload.write_part(
                    f"video/{video_part_name}.mp4",
                    video_source,
                    max_bytes=max_video_bytes,
                )
            committed_files = upload.commit()
            committed = True

        package_with_paths = replace(
            package,
            package_fingerprint=calculate_bundle_fingerprint(committed_files),
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


class TableObservationPersister:
    """Store canonical table-observation bytes and database metadata together."""

    def __init__(self, repository: EvidenceRepository, storage: EvidenceStorage) -> None:
        self.repository = repository
        self.storage = storage

    def persist(
        self, observation: TableObservation, observation_bytes: bytes
    ) -> StoredTableObservation:
        """Stage the observation, insert metadata, and clean up on failure."""

        relative_path = f"table-observations/{observation.observation_id}/observation.json"
        database_insert: TableObservationInsert | None = None
        with self.storage.start_table_observation(observation.observation_id) as staged:
            staged.write_observation(observation_bytes)
            database_insert = self.repository.insert_table_observation(
                observation,
                observation_bytes,
                relative_path,
            )
            if not database_insert.created:
                return database_insert.observation
            try:
                staged.commit()
            except BaseException:
                self.repository.delete_table_observation(
                    observation.observation_id,
                    observation_sha256=database_insert.observation.observation_sha256,
                )
                raise
        return database_insert.observation


__all__ = ["EvidencePackagePersister", "TableObservationPersister"]
