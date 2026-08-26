import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from dokodetector_backend.contract import (
    EvidenceManifest,
    calculate_package_fingerprint,
    parse_manifest_bytes,
    validate_manifest,
)
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
from dokodetector_backend.storage import EvidenceStorage

BACKEND_ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "evidence" / "v1"
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
            relative_path=f"evidence/{manifest.package_id}/frames/{frame.part_name}.jpg",
        )
        for frame in manifest.frames
    )
    return StoredPackage.from_manifest(
        manifest,
        raw,
        package_fingerprint=calculate_package_fingerprint(raw, manifest.frames),
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
    assert reloaded.frames[0].relative_path == (f"evidence/{PACKAGE_ID}/frames/frame_00.jpg")


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


def test_persister_links_existing_files_to_database_rows(tmp_path) -> None:
    raw, manifest = load_fixture("example-complete")
    database_url = f"sqlite:///{tmp_path / 'stored.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    repository = EvidenceRepository(create_database_engine(database_url))
    storage = EvidenceStorage(tmp_path)
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

    stored = persister.persist(package, raw, frame_sources)
    reloaded = repository.get_package(package.package_id)

    assert reloaded == stored
    assert reloaded is not None
    assert (tmp_path / f"{stored.frames[0].relative_path}").read_bytes() == frame_sources[
        stored.frames[0].part_name
    ]
    assert (tmp_path / "evidence" / str(PACKAGE_ID) / "manifest.json").read_bytes() == raw
    assert (
        stored.frames[0].sha256
        == hashlib.sha256(frame_sources[stored.frames[0].part_name]).hexdigest()
    )


def test_failed_database_insert_removes_renamed_files(tmp_path) -> None:
    raw, manifest = load_fixture("example-complete")
    database_url = f"sqlite:///{tmp_path / 'failure.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    repository = EvidenceRepository(create_database_engine(database_url))
    storage = EvidenceStorage(tmp_path)
    persister = EvidencePackagePersister(repository, storage)

    first_package = package_record(raw, manifest)
    persister.persist(
        first_package,
        raw,
        {frame.part_name: b"first-frame" for frame in manifest.frames},
    )

    second_package = package_record(
        raw,
        manifest,
        package_id=UUID("550e8400-e29b-41d4-a716-446655440099"),
    )
    with pytest.raises(LogicalEventConflict):
        persister.persist(
            second_package,
            raw,
            {frame.part_name: b"second-frame" for frame in manifest.frames},
        )

    assert repository.get_package(second_package.package_id) is None
    assert not storage.package_path(second_package.package_id).exists()
    assert list(storage.evidence_root.glob(".upload-*")) == []
