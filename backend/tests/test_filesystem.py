from __future__ import annotations

import json
from pathlib import Path

import pytest

from dokodetector_backend.filesystem import (
    FilesystemPathError,
    atomic_write_json,
    commit_staged_directory,
    contained_path,
    enumerate_resource_directories,
    staging_directory,
)


def test_contained_path_rejects_traversal_and_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "nested").mkdir()
    (root / "nested" / "link").symlink_to(outside, target_is_directory=True)

    assert contained_path(root, "nested/value.json") == root / "nested/value.json"
    with pytest.raises(FilesystemPathError):
        contained_path(root, "../outside.txt")
    with pytest.raises(FilesystemPathError):
        contained_path(root, "nested/link/value.json")


def test_staged_directory_publishes_only_after_validation(tmp_path: Path) -> None:
    root = tmp_path / "resources"
    destination = root / "resource-001"

    with staging_directory(root, prefix=".upload-") as staged:
        (staged / "manifest.json").write_text('{"id":"resource-001"}', encoding="utf-8")
        commit_staged_directory(
            staged,
            destination,
            validate=lambda path: json.loads((path / "manifest.json").read_text()),
        )

    assert destination.is_dir()
    assert (destination / "manifest.json").read_text(encoding="utf-8") == '{"id":"resource-001"}'
    assert list(root.glob(".upload-*")) == []


def test_failed_staged_validation_leaves_no_visible_resource(tmp_path: Path) -> None:
    root = tmp_path / "resources"
    destination = root / "resource-001"

    with pytest.raises(ValueError, match="missing manifest"), staging_directory(root) as staged:
        (staged / "partial.json").write_text("{}", encoding="utf-8")
        commit_staged_directory(
            staged,
            destination,
            validate=lambda path: (_ for _ in ()).throw(ValueError("missing manifest")),
        )

    assert not destination.exists()
    assert list(root.glob(".staging-*")) == []


def test_failed_staged_rename_leaves_no_visible_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "resources"
    destination = root / "resource-001"

    def fail_rename(source: Path, target: Path) -> None:
        raise OSError("simulated directory publication failure")

    monkeypatch.setattr("dokodetector_backend.filesystem.os.rename", fail_rename)
    with pytest.raises(OSError, match="simulated directory publication failure"), staging_directory(
        root
    ) as staged:
        (staged / "manifest.json").write_text('{"id":"resource-001"}', encoding="utf-8")
        commit_staged_directory(staged, destination)

    assert not destination.exists()
    assert list(root.glob(".staging-*")) == []


def test_atomic_json_replacement_keeps_old_bytes_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    atomic_write_json(path, {"state": "old", "revision": 1})
    original_replace = __import__("dokodetector_backend.filesystem", fromlist=["os"]).os.replace

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr("dokodetector_backend.filesystem.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated replacement failure"):
        atomic_write_json(path, {"state": "new", "revision": 2})

    assert json.loads(path.read_text(encoding="utf-8")) == {"revision": 1, "state": "old"}
    assert list(tmp_path.glob(".state.json.*.tmp")) == []
    assert original_replace is not None


def test_atomic_json_validation_happens_before_replacement(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    atomic_write_json(path, {"state": "old"})

    with pytest.raises(ValueError, match="state is not supported"):
        atomic_write_json(
            path,
            {"state": "new"},
            validate=lambda value: (_ for _ in ()).throw(ValueError("state is not supported")),
        )

    assert json.loads(path.read_text(encoding="utf-8")) == {"state": "old"}


def test_atomic_json_rejects_a_symlinked_parent(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(FilesystemPathError, match="symlink"):
        atomic_write_json(linked_parent / "state.json", {"state": "new"})

    assert not (outside / "state.json").exists()


def test_directory_enumeration_is_sorted_and_reports_invalid_entries(tmp_path: Path) -> None:
    root = tmp_path / "resources"
    (root / "b").mkdir(parents=True)
    (root / "a").mkdir()
    (root / ".upload-abandoned").mkdir()
    (root / "invalid").mkdir()
    (root / "file.txt").write_text("not a directory", encoding="utf-8")

    def validate(path: Path) -> None:
        if path.name == "invalid":
            raise ValueError("manifest.json is missing")

    result = enumerate_resource_directories(root, validate=validate)

    assert [path.name for path in result.paths] == ["a", "b"]
    assert [(item.path.name, item.reason) for item in result.diagnostics] == [
        (".upload-abandoned", "staging directory ignored"),
        ("file.txt", "non-directory resource ignored"),
        ("invalid", "invalid resource: manifest.json is missing"),
    ]
