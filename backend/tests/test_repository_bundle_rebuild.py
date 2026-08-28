from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dokodetector_backend.repository import create_database_engine, upgrade_database
from dokodetector_backend.repository_bundle_repository import (
    RepositoryBundleRebuildError,
    RepositoryBundleRepository,
)
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


def test_rebuild_rejects_changed_canonical_member_before_database_mutation(tmp_path: Path) -> None:
    intake_root = tmp_path / "intake"
    _copy_fixture("both", intake_root)
    source_path = intake_root / "recording-both" / "source-record.json"
    source = json.loads(source_path.read_text())
    source["notes"] = "changed"
    source_path.write_text(json.dumps(source))
    database_url = f"sqlite:///{tmp_path / 'repository.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    repository = RepositoryBundleRepository(create_database_engine(database_url))

    with pytest.raises(RepositoryBundleRebuildError):
        repository.rebuild_from_intake(RepositoryBundleStorage(intake_root))
    assert repository.get("recording-both") is None
