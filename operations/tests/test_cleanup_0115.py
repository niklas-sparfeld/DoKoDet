from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import cleanup_0115

ROOT = "data/operations-recovery/0108-m10-20261105/recording-videos"


def _write(path: Path, content: bytes) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return len(content), hashlib.sha256(content).hexdigest()


def _fixture(tmp_path: Path, *, authorized: bool = True) -> tuple[Path, Path, Path, dict]:
    repo = tmp_path / "repo"
    root = repo / ROOT
    size, digest = _write(root / "clip.mov", b"recovery copy")
    ref_size, ref_digest = _write(repo / "data/intake/recordings/clip.mov", b"recovery copy")
    candidate = {
        "path": f"{ROOT}/clip.mov",
        "bytes": size,
        "sha256": digest,
        "status": "Candidate for M3 only; retain in M1.",
        "intake_path": "data/intake/recordings/clip.mov",
        "references": [
            {
                "path": "data/intake/recordings/clip.mov",
                "bytes": ref_size,
                "sha256": ref_digest,
            }
        ],
    }
    if authorized:
        candidate["authorization"] = "authorized"
    manifest = {
        "schema_version": "0115-cleanup-plan/v1",
        "candidates": [candidate],
        "decision": "Authorized for fixture only" if authorized else "No deletion authorized",
        "deletion_authorized": authorized,
        "references_complete": authorized,
        "unknowns": [] if authorized else ["unknown reference"],
        "retained_paths": [{"path": "data/intake/recordings", "reason": "source"}],
    }
    manifest_path = repo / "docs/cleanup-plan.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return repo, root, manifest_path, manifest


def _plan(repo: Path, manifest: Path) -> str:
    args = type(
        "Args",
        (),
        {
            "repo_root": repo,
            "manifest": manifest,
            "cleanup_root": ROOT,
            "output": None,
        },
    )()
    return cleanup_0115._plan(args).relative_to(repo).as_posix()


def _apply(repo: Path, plan: str) -> None:
    args = type("Args", (), {"repo_root": repo, "plan": plan})()
    cleanup_0115._apply(args)


def test_plan_is_dry_run_and_writes_only_inside_selected_root(tmp_path: Path) -> None:
    repo, root, manifest_path, _ = _fixture(tmp_path)
    before = (root / "clip.mov").read_bytes()
    before_paths = {path.relative_to(repo).as_posix() for path in repo.rglob("*")}

    plan_relative = _plan(repo, manifest_path)

    plan = json.loads((repo / plan_relative).read_text())
    assert plan["candidate_count"] == 1
    assert plan["apply_permitted"] is True
    assert (root / "clip.mov").read_bytes() == before
    assert (repo / plan_relative).is_relative_to(root)
    new_paths = {path.relative_to(repo).as_posix() for path in repo.rglob("*")} - before_paths
    assert new_paths == {f"{ROOT}/.cleanup-plans", plan_relative}


def test_unknown_references_and_changed_protected_dependency_reject_apply_or_plan(
    tmp_path: Path,
) -> None:
    repo, root, manifest_path, _ = _fixture(tmp_path, authorized=False)
    plan_relative = _plan(repo, manifest_path)
    with pytest.raises(cleanup_0115.CleanupError, match="does not explicitly authorize"):
        _apply(repo, plan_relative)
    assert (root / "clip.mov").exists()

    repo2, _, manifest_path2, _ = _fixture(tmp_path / "changed")
    (repo2 / "data/intake/recordings/clip.mov").write_bytes(b"changed source")
    with pytest.raises(cleanup_0115.CleanupError, match="protected dependency changed"):
        _plan(repo2, manifest_path2)


def test_changed_manifest_rejects_stale_plan(tmp_path: Path) -> None:
    repo, root, manifest_path, manifest = _fixture(tmp_path)
    plan_relative = _plan(repo, manifest_path)
    manifest["note"] = "changed"
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(cleanup_0115.CleanupError, match="source manifest changed"):
        _apply(repo, plan_relative)
    assert (root / "clip.mov").exists()


def test_symlink_escape_is_rejected_without_touching_target(tmp_path: Path) -> None:
    repo, root, manifest_path, manifest = _fixture(tmp_path)
    outside = tmp_path / "outside.mov"
    outside.write_bytes(b"do not touch")
    (root / "escape.mov").symlink_to(outside)
    manifest["candidates"].append(
        {
            "path": f"{ROOT}/escape.mov",
            "bytes": len(b"do not touch"),
            "sha256": hashlib.sha256(b"do not touch").hexdigest(),
            "authorization": "authorized",
            "references": [],
        }
    )
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(cleanup_0115.CleanupError, match="symlink path rejected"):
        _plan(repo, manifest_path)
    assert outside.read_bytes() == b"do not touch"


def test_active_open_file_blocks_apply(tmp_path: Path) -> None:
    repo, root, manifest_path, _ = _fixture(tmp_path)
    plan_relative = _plan(repo, manifest_path)
    with (
        (root / "clip.mov").open("rb"),
        pytest.raises(cleanup_0115.CleanupError, match="open files exist"),
    ):
        _apply(repo, plan_relative)
    assert (root / "clip.mov").exists()


def test_interrupted_apply_resumes_and_repeated_apply_is_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, root, manifest_path, manifest = _fixture(tmp_path)
    second = root / "second.mov"
    second_size, second_digest = _write(second, b"second clip")
    source = repo / "data/intake/recordings/second.mov"
    _write(source, b"second clip")
    manifest["candidates"].append(
        {
            "path": f"{ROOT}/second.mov",
            "bytes": second_size,
            "sha256": second_digest,
            "authorization": "authorized",
            "references": [
                {
                    "path": "data/intake/recordings/second.mov",
                    "bytes": second_size,
                    "sha256": second_digest,
                }
            ],
        }
    )
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    plan_relative = _plan(repo, manifest_path)
    original_atomic_json = cleanup_0115._atomic_json
    interrupted = False

    def fail_after_unlink(root_path: Path, path: Path, document: dict) -> None:
        nonlocal interrupted
        if not interrupted and document.get("candidates", [{}])[0].get("status") == "removed":
            interrupted = True
            raise OSError("simulated interruption after unlink")
        original_atomic_json(root_path, path, document)

    monkeypatch.setattr(cleanup_0115, "_atomic_json", fail_after_unlink)
    with pytest.raises(OSError, match="simulated interruption"):
        _apply(repo, plan_relative)
    monkeypatch.setattr(cleanup_0115, "_atomic_json", original_atomic_json)

    _apply(repo, plan_relative)
    assert not (root / "clip.mov").exists()
    assert not second.exists()
    receipt_paths = list((root / ".cleanup-receipts").glob("*.json"))
    assert len(receipt_paths) == 1
    receipt = json.loads(receipt_paths[0].read_text())
    assert receipt["status"] == "complete"
    assert len(receipt["observed"]) == 2

    _apply(repo, plan_relative)
    assert len(list((root / ".cleanup-receipts").glob("*.json"))) == 1
    assert all(entry["status"] == "removed" for entry in receipt["candidates"])


def test_candidate_replacement_with_same_bytes_is_stale(tmp_path: Path) -> None:
    repo, root, manifest_path, _ = _fixture(tmp_path)
    plan_relative = _plan(repo, manifest_path)
    candidate = root / "clip.mov"
    replacement = root / "replacement.mov"
    replacement.write_bytes(candidate.read_bytes())
    candidate.unlink()
    replacement.rename(candidate)
    os.utime(candidate, ns=(candidate.stat().st_atime_ns, candidate.stat().st_mtime_ns + 1))

    with pytest.raises(cleanup_0115.CleanupError, match="identities changed"):
        _apply(repo, plan_relative)
    assert candidate.exists()
