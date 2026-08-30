from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from dokodetector_backend.repository import create_database_engine, upgrade_database
from dokodetector_backend.repository_bundle_repository import RepositoryBundleRepository
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage

BACKEND_ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1"


def _copy_fixture(source: str, root: Path) -> None:
    shutil.copytree(FIXTURE_ROOT / source, root / "recording-both")


def test_rebuild_recreates_index_from_canonical_files(tmp_path: Path) -> None:
    intake_root = tmp_path / "intake"
    _copy_fixture("both", intake_root)
    database_url = f"sqlite:///{tmp_path / 'repository.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    repository = RepositoryBundleRepository(create_database_engine(database_url))

    rebuilt = repository.rebuild_from_intake(RepositoryBundleStorage(intake_root))

    assert [item.recording_id for item in rebuilt] == ["recording-both"]
    stored = repository.get("recording-both")
    assert stored is not None
    assert (
        stored.source_sha256
        == json.loads((intake_root / "recording-both" / "manifest.json").read_text())[
            "source_sha256"
        ]
    )

    repository.rebuild_from_intake(RepositoryBundleStorage(intake_root))
    assert repository.get("recording-both") == stored


def test_rebuild_skips_changed_canonical_member_before_database_mutation(tmp_path: Path) -> None:
    intake_root = tmp_path / "intake"
    _copy_fixture("both", intake_root)
    source_path = intake_root / "recording-both" / "source-record.json"
    source = json.loads(source_path.read_text())
    source["notes"] = "changed"
    source_path.write_text(json.dumps(source))
    database_url = f"sqlite:///{tmp_path / 'repository.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    repository = RepositoryBundleRepository(create_database_engine(database_url))

    rebuilt = repository.rebuild_from_intake(RepositoryBundleStorage(intake_root))

    assert rebuilt == ()
    assert repository.get("recording-both") is None


def test_rebuild_skips_invalid_bundle_and_keeps_valid_bundle(tmp_path: Path, caplog) -> None:
    intake_root = tmp_path / "intake"
    _copy_fixture("both", intake_root)
    shutil.copytree(FIXTURE_ROOT / "both", intake_root / "recording-invalid")
    source_path = intake_root / "recording-invalid" / "source-record.json"
    source = json.loads(source_path.read_text())
    source["notes"] = "changed"
    source_path.write_text(json.dumps(source))
    database_url = f"sqlite:///{tmp_path / 'repository.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    repository = RepositoryBundleRepository(create_database_engine(database_url))

    rebuilt = repository.rebuild_from_intake(RepositoryBundleStorage(intake_root))

    assert [item.recording_id for item in rebuilt] == ["recording-both"]
    assert repository.get("recording-both") is not None
    assert repository.get("recording-invalid") is None
    warning = next(
        record for record in caplog.records if record.msg == "repository_bundle_rebuild_skipped"
    )
    assert warning.levelno == logging.WARNING
    assert warning.event_name == "repository_bundle_rebuild_skipped"
    assert warning.event_fields["recording_id"] == "recording-invalid"


def test_rebuild_ignores_macos_metadata_file(tmp_path: Path) -> None:
    intake_root = tmp_path / "intake"
    _copy_fixture("both", intake_root)
    (intake_root / "recording-both" / ".DS_Store").write_bytes(b"metadata")
    database_url = f"sqlite:///{tmp_path / 'repository.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    repository = RepositoryBundleRepository(create_database_engine(database_url))

    rebuilt = repository.rebuild_from_intake(RepositoryBundleStorage(intake_root))

    assert [item.recording_id for item in rebuilt] == ["recording-both"]
    assert repository.get("recording-both") is not None
