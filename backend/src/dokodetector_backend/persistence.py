"""Coordinate atomic publication of evidence and observation files."""

from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO
from uuid import UUID

from dokodetector_backend.evidence_package_store import EvidencePackageStore
from dokodetector_backend.repository import StoredPackage, StoredTableObservation
from dokodetector_backend.table_observation_store import TableObservationStore

if TYPE_CHECKING:
    from table_evidence_analyzer import TableObservation


class EvidencePackagePersister:
    """Validate and publish one complete evidence-package bundle."""

    def __init__(self, store: EvidencePackageStore) -> None:
        self.store = store
        self.storage = store.storage

    def persist(
        self,
        package_id: UUID,
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
    ) -> tuple[StoredPackage, bool]:
        """Stage and publish one package without a metadata database write."""

        with self.storage.start_package(package_id) as upload:
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
            for part_name in frame_sources:
                upload.write_part(
                    f"frames/{part_name}.jpg",
                    frame_sources[part_name],
                    max_bytes=max_frame_bytes,
                )
            if video_source is not None:
                if video_part_name is None:
                    raise ValueError("A video part name is required for video bytes.")
                upload.write_part(
                    f"video/{video_part_name}.mp4",
                    video_source,
                    max_bytes=max_video_bytes,
                )
            return self.store.publish(upload)


class TableObservationPersister:
    """Validate and publish one immutable table observation."""

    def __init__(self, store: TableObservationStore) -> None:
        self.store = store

    def persist(
        self, observation: TableObservation, observation_bytes: bytes
    ) -> StoredTableObservation:
        """Stage and publish one observation without database compensation."""

        return self.store.publish(observation, observation_bytes)[0]


__all__ = ["EvidencePackagePersister", "TableObservationPersister"]
