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
