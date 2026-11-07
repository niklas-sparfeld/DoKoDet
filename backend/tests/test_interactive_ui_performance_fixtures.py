from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parents[1] / "scripts" / "materialize_interactive_ui_performance_fixtures.py"
)
SPEC = importlib.util.spec_from_file_location("interactive_performance_fixtures", SCRIPT)
assert SPEC and SPEC.loader
fixtures = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixtures)


def test_generated_fixture_is_reproducible_and_valid(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    fixtures.materialize(first, "small")
    fixtures.materialize(second, "small")

    first_files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    second_files = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    assert first_files == second_files
    assert [p.read_bytes() for p in (first / name for name in first_files)] == [
        p.read_bytes() for p in (second / name for name in second_files)
    ]
    manifest = fixtures.validate(first)
    assert manifest["seed"] == fixtures.SEED
    assert manifest["sizes"] == fixtures.PROFILES["small"]


def test_fixture_validation_fails_for_missing_media(tmp_path: Path) -> None:
    root = tmp_path / "fixture"
    fixtures.materialize(root, "small")
    (root / "media/perf-00000.bin").unlink()

    with pytest.raises(ValueError, match="Missing required fixture asset: media/perf-00000.bin"):
        fixtures.validate(root)


def test_fixture_validation_rejects_broken_lineage_closure(tmp_path: Path) -> None:
    root = tmp_path / "fixture"
    fixtures.materialize(root, "small")
    manifest_path = root / "fixture-manifest.json"
    fixture_manifest = json.loads(manifest_path.read_text())
    relative = "pipeline/nodes/node-000001/manifest.json"
    node_path = root / relative
    node = json.loads(node_path.read_text())
    node["source_node_id"] = "missing-node"
    node_path.write_bytes(fixtures._json_bytes(node))
    entry = next(item for item in fixture_manifest["files"] if item["path"] == relative)
    content = node_path.read_bytes()
    entry["sha256"] = hashlib.sha256(content).hexdigest()
    entry["byte_length"] = len(content)
    manifest_path.write_bytes(fixtures._json_bytes(fixture_manifest))

    with pytest.raises(ValueError, match="Missing lineage node missing-node"):
        fixtures.validate(root)


def test_generated_fixture_rejects_repository_storage_target() -> None:
    target = Path(__file__).parents[2] / ".runtime/performance-fixtures"

    with pytest.raises(ValueError, match="Disposable output must be outside the repository"):
        fixtures.materialize(target, "small")


def test_hard_snapshot_requires_every_content_addressed_asset(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Missing required hard snapshot asset"):
        fixtures.validate_hard_snapshot(tmp_path / "cache")
