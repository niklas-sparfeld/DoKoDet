from pathlib import Path

import pytest

from dokodetector_backend.storage_consolidation import (
    StorageConsolidationError,
    consolidate_storage,
)


def test_consolidation_moves_legacy_files_and_deduplicates_equal_files(tmp_path: Path) -> None:
    legacy_reference = (
        tmp_path / "backend" / "data" / "operations" / "pipeline-references" / "recording-1"
    )
    legacy_reference.mkdir(parents=True)
    (legacy_reference / "state.json").write_text("legacy", encoding="utf-8")
    central_operations = tmp_path / "data" / "operations"
    central_operations.mkdir(parents=True)
    duplicate = central_operations / "same.json"
    duplicate.write_text("same", encoding="utf-8")
    legacy_duplicate = tmp_path / "backend" / "data" / "operations" / "same.json"
    legacy_duplicate.write_text("same", encoding="utf-8")

    report = consolidate_storage(tmp_path, apply=True)

    assert "data/operations/pipeline-references/recording-1/state.json" in report.moved
    assert "data/operations/same.json" in report.deduplicated
    assert (
        central_operations / "pipeline-references/recording-1/state.json"
    ).read_text() == "legacy"
    assert not legacy_duplicate.exists()


def test_consolidation_rejects_different_central_data_before_moving(tmp_path: Path) -> None:
    legacy_root = tmp_path / "backend" / "data" / "operations"
    legacy_root.mkdir(parents=True)
    (legacy_root / "same.json").write_text("legacy", encoding="utf-8")
    central_root = tmp_path / "data" / "operations"
    central_root.mkdir(parents=True)
    (central_root / "same.json").write_text("central", encoding="utf-8")
    (legacy_root / "new.json").write_text("new", encoding="utf-8")

    with pytest.raises(StorageConsolidationError, match="central data already differs"):
        consolidate_storage(tmp_path, apply=True)

    assert (legacy_root / "new.json").exists()


def test_consolidation_moves_durable_repository_runtime_records_to_operations(
    tmp_path: Path,
) -> None:
    revision = tmp_path / ".runtime" / "pipeline" / "revisions" / "revision-1"
    revision.mkdir(parents=True)
    (revision / "manifest.json").write_text("manifest", encoding="utf-8")
    observation = tmp_path / ".runtime" / "table-observations" / "observation-1"
    observation.mkdir(parents=True)
    (observation / "observation.json").write_text("observation", encoding="utf-8")
    cache = tmp_path / ".runtime" / "pipeline" / "derived-views" / "cache-1"
    cache.mkdir(parents=True)
    (cache / "content.bin").write_bytes(b"cache")

    report = consolidate_storage(tmp_path, apply=True)

    assert "data/operations/pipeline/revisions/revision-1/manifest.json" in report.moved
    assert "data/operations/table-observations/observation-1/observation.json" in report.moved
    assert (tmp_path / "data/operations/pipeline/revisions/revision-1/manifest.json").is_file()
    assert (
        tmp_path / "data/operations/table-observations/observation-1/observation.json"
    ).is_file()
    assert (cache / "content.bin").is_file()
