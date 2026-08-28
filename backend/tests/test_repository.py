import hashlib
import json
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from dokodetector_backend.api import _build_evidence_package_bundle
from dokodetector_backend.contract import (
    EvidenceManifest,
    calculate_package_fingerprint,
    parse_manifest_bytes,
    validate_manifest,
)
from dokodetector_backend.evidence_package_storage import EvidencePackageStorage
from dokodetector_backend.persistence import EvidencePackagePersister
from dokodetector_backend.repository import (
    EvidenceRepository,
    LogicalEventConflict,
    PackageConflict,
    StoredFrame,
    StoredPackage,
    create_database_engine,
    upgrade_database,
)

BACKEND_ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "evidence" / "v2"
PACKAGE_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


def load_fixture(name: str) -> tuple[bytes, EvidenceManifest]:
    raw = (FIXTURE_ROOT / name / "manifest.json").read_bytes()
    return raw, parse_manifest_bytes(raw)


def package_record(
    raw: bytes,
    manifest: EvidenceManifest,
    *,
    package_id: UUID | None = None,
    event_sequence: int | None = None,
) -> StoredPackage:
    if package_id is not None or event_sequence is not None:
        payload = manifest.model_dump(mode="json")
        if package_id is not None:
            payload["package_id"] = str(package_id)
        if event_sequence is not None:
            payload["session"]["event_sequence"] = event_sequence
        manifest = validate_manifest(payload)

    frames = tuple(
        StoredFrame.from_manifest(
            frame,
            relative_path=f"frames/{frame.part_name}.jpg",
        )
        for frame in manifest.frames
    )
    return StoredPackage.from_manifest(
        manifest,
        raw,
        package_fingerprint=calculate_package_fingerprint(
            raw,
            manifest.frames,
            video_snippet=manifest.video_snippet,
        ),
        frames=frames,
        received_at=datetime(2026, 8, 26, 19, 0, tzinfo=timezone.utc),
    )


@pytest.fixture()
def repository(tmp_path) -> EvidenceRepository:
    database_path = tmp_path / "evidence.sqlite"
    database_url = f"sqlite:///{database_path}"
    upgrade_database(BACKEND_ROOT, database_url)
    return EvidenceRepository(create_database_engine(database_url))


def test_package_and_frame_rows_survive_a_database_restart(tmp_path) -> None:
    raw, manifest = load_fixture("example-complete")
    package = package_record(raw, manifest)
    database_url = f"sqlite:///{tmp_path / 'restart.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)

    first_repository = EvidenceRepository(create_database_engine(database_url))
    first_repository.insert_package(package)
    first_repository.engine.dispose()

    second_repository = EvidenceRepository(create_database_engine(database_url))
    reloaded = second_repository.get_package(PACKAGE_ID)

    assert reloaded == package
    assert reloaded is not None
    assert reloaded.frames[0].relative_path == "frames/frame_00.jpg"


def test_repository_enforces_unique_logical_event(repository: EvidenceRepository) -> None:
    complete_raw, complete_manifest = load_fixture("example-complete")
    first_package = package_record(complete_raw, complete_manifest)
    second_package = package_record(
        complete_raw,
        complete_manifest,
        package_id=UUID("550e8400-e29b-41d4-a716-446655440099"),
    )

    repository.insert_package(first_package)

    with pytest.raises(LogicalEventConflict):
        repository.insert_package(second_package)

    assert repository.get_package(second_package.package_id) is None
    assert (
        repository.get_by_logical_event(first_package.session_id, first_package.event_sequence)
        == first_package
    )


def test_repository_rejects_duplicate_package_id(repository: EvidenceRepository) -> None:
    raw, manifest = load_fixture("example-complete")
    package = package_record(raw, manifest)
    repository.insert_package(package)

    with pytest.raises(PackageConflict):
        repository.insert_package(package)


def test_repository_rebuilds_package_rows_from_canonical_intake(tmp_path) -> None:
    intake_root = tmp_path / "evidence-packages"
    shutil.copytree(
        Path(__file__).parents[2]
        / "fixtures"
        / "repository-intake"
        / "v1"
        / "evidence-package-complete",
        intake_root / str(PACKAGE_ID),
    )
    database_url = f"sqlite:///{tmp_path / 'rebuild.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    repository = EvidenceRepository(create_database_engine(database_url))

    rebuilt = repository.rebuild_from_intake(EvidencePackageStorage(intake_root))

    assert [item.package_id for item in rebuilt] == [PACKAGE_ID]
    stored = repository.get_package(PACKAGE_ID)
    assert stored is not None
    assert stored.package_fingerprint == rebuilt[0].package_fingerprint
    assert stored.frames[0].relative_path == "frames/frame_00.jpg"


def test_persister_links_existing_files_to_database_rows(tmp_path) -> None:
    raw, manifest = load_fixture("example-complete")
    database_url = f"sqlite:///{tmp_path / 'stored.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    repository = EvidenceRepository(create_database_engine(database_url))
    storage = EvidencePackageStorage(tmp_path / "evidence-packages")
    persister = EvidencePackagePersister(repository, storage)
    frame_sources = {
        frame.part_name: f"bytes for {frame.part_name}".encode() for frame in manifest.frames
    }
    package = package_record(raw, manifest)
    package = replace(
        package,
        frames=tuple(
            replace(
                frame,
                byte_length=len(frame_sources[frame.part_name]),
                sha256=hashlib.sha256(frame_sources[frame.part_name]).hexdigest(),
            )
            for frame in package.frames
        ),
    )
    video_source = (FIXTURE_ROOT / "example-complete" / "snippet.mp4").read_bytes()
    package_record_bytes, task_enrollment_bytes, lineage_bytes = _metadata(
        package.package_id, package.session_id
    )
    bundle_manifest_bytes = _build_evidence_package_bundle(
        package_id=package.package_id,
        source_asset_id=f"source-evidence-{package.package_id}",
        manifest_bytes=raw,
        package_record_bytes=package_record_bytes,
        task_enrollment_bytes=task_enrollment_bytes,
        lineage_bytes=lineage_bytes,
        manifest=manifest,
        frame_sources=frame_sources,
        video_bytes=video_source,
    )

    stored = persister.persist(
        package,
        evidence_manifest_source=raw,
        package_record_source=package_record_bytes,
        task_enrollment_source=task_enrollment_bytes,
        lineage_source=lineage_bytes,
        bundle_manifest_source=bundle_manifest_bytes,
        frame_sources=frame_sources,
        video_source=video_source,
        video_part_name=manifest.video_snippet.part_name,
    )
    reloaded = repository.get_package(package.package_id)

    assert reloaded == stored
    assert reloaded is not None
    assert (
        storage.package_path(stored.package_id) / stored.frames[0].relative_path
    ).read_bytes() == frame_sources[stored.frames[0].part_name]
    assert (storage.package_path(PACKAGE_ID) / "evidence-manifest.json").read_bytes() == raw
    assert (
        stored.frames[0].sha256
        == hashlib.sha256(frame_sources[stored.frames[0].part_name]).hexdigest()
    )
    assert (
        storage.package_path(PACKAGE_ID) / "video" / f"{manifest.video_snippet.part_name}.mp4"
    ).read_bytes() == video_source


def test_failed_database_insert_removes_renamed_files(tmp_path) -> None:
    raw, manifest = load_fixture("example-complete")
    database_url = f"sqlite:///{tmp_path / 'failure.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    repository = EvidenceRepository(create_database_engine(database_url))
    storage = EvidencePackageStorage(tmp_path / "evidence-packages")
    persister = EvidencePackagePersister(repository, storage)

    first_package = package_record(raw, manifest)
    video_source = (FIXTURE_ROOT / "example-complete" / "snippet.mp4").read_bytes()
    package_record_bytes, task_enrollment_bytes, lineage_bytes = _metadata(
        first_package.package_id, first_package.session_id
    )
    bundle_manifest_bytes = _build_evidence_package_bundle(
        package_id=first_package.package_id,
        source_asset_id=f"source-evidence-{first_package.package_id}",
        manifest_bytes=raw,
        package_record_bytes=package_record_bytes,
        task_enrollment_bytes=task_enrollment_bytes,
        lineage_bytes=lineage_bytes,
        manifest=manifest,
        frame_sources={frame.part_name: b"first-frame" for frame in manifest.frames},
        video_bytes=video_source,
    )
    persister.persist(
        first_package,
        evidence_manifest_source=raw,
        package_record_source=package_record_bytes,
        task_enrollment_source=task_enrollment_bytes,
        lineage_source=lineage_bytes,
        bundle_manifest_source=bundle_manifest_bytes,
        frame_sources={frame.part_name: b"first-frame" for frame in manifest.frames},
        video_source=video_source,
        video_part_name=manifest.video_snippet.part_name,
    )

    second_package = package_record(
        raw,
        manifest,
        package_id=UUID("550e8400-e29b-41d4-a716-446655440099"),
    )
    with pytest.raises(LogicalEventConflict):
        persister.persist(
            second_package,
            evidence_manifest_source=raw,
            package_record_source=package_record_bytes,
            task_enrollment_source=task_enrollment_bytes,
            lineage_source=lineage_bytes,
            bundle_manifest_source=bundle_manifest_bytes,
            frame_sources={frame.part_name: b"second-frame" for frame in manifest.frames},
            video_source=video_source,
            video_part_name=manifest.video_snippet.part_name,
        )

    assert repository.get_package(second_package.package_id) is None
    assert not storage.package_path(second_package.package_id).exists()
    assert list(storage.root.glob(".upload-*")) == []


def _metadata(package_id: UUID, session_id: UUID) -> tuple[bytes, bytes, bytes]:
    package_value = str(package_id)
    source_asset_id = f"source-evidence-{package_value}"

    def encode(value: dict[str, object]) -> bytes:
        return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()

    record = {
        "schema_version": "evidence-package-record/v1",
        "package_id": package_value,
        "source_asset_id": source_asset_id,
        "source_permission": "project_use",
        "allowed_uses": ["evaluation"],
        "retention_state": "active",
        "notes": "test",
    }
    enrollment = {
        "schema_version": "task-enrollment/v1",
        "source_asset_id": source_asset_id,
        "enrollments": [
            {
                "task_enrollment_id": f"enrollment-{package_value}-cardevent",
                "task": "cardevent_event_detection",
                "disposition": "selected",
                "lifecycle_state": "intake",
                "operator": "test",
                "created_at_utc": "2026-01-01T00:00:00Z",
                "reason": None,
            },
            {
                "task_enrollment_id": f"enrollment-{package_value}-table",
                "task": "table_evidence_analysis",
                "disposition": "selected",
                "lifecycle_state": "intake",
                "operator": "test",
                "created_at_utc": "2026-01-01T00:00:00Z",
                "reason": None,
            },
        ],
    }
    lineage = {
        "schema_version": "evidence-package-lineage/v1",
        "package_id": package_value,
        "parent_source_asset_id": None,
        "parent_recording_id": None,
        "parent_video_id": None,
        "session_id": str(session_id),
    }
    return encode(record), encode(enrollment), encode(lineage)
