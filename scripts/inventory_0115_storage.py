"""Print a bounded, repeatable storage inventory for Epic 0115 M0."""

from __future__ import annotations

import argparse
import collections
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any


def _command(repo: Path, *args: str) -> str:
    result = subprocess.run(args, cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout


def _worktrees(repo: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in _command(repo, "git", "worktree", "list", "--porcelain").splitlines():
        if not line:
            if current:
                rows.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value if value else True
    if current:
        rows.append(current)
    return rows


def _du_kib(path: Path) -> int | None:
    if not path.exists():
        return None
    result = subprocess.run(
        ["du", "-sk", str(path)], check=True, capture_output=True, text=True
    )
    return int(result.stdout.split()[0])


def _summaries(parent: Path, roots: list[tuple[str, Path]], top: int) -> dict[str, Any]:
    stats: dict[str, dict[str, Any]] = {}
    for name, path in roots:
        stats[name] = {
            "path": str(path),
            "allocated_kib_du": _du_kib(path),
            "regular_files": 0,
            "logical_bytes": 0,
            "path_allocated_bytes": 0,
            "symlinks": 0,
            "hard_link_paths": 0,
            "extensions": collections.Counter(),
            "largest": [],
        }

    prefixes = [
        (name, path.relative_to(parent))
        for name, path in roots
        if path != parent and path.is_relative_to(parent)
    ]
    parents = [name for name, path in roots if path == parent]
    for base, dirs, files in os.walk(parent, followlinks=False):
        base_path = Path(base)
        dirs[:] = [d for d in dirs if not (base_path / d).is_symlink()]
        for filename in files:
            path = base_path / filename
            try:
                info = path.lstat()
            except OSError:
                continue
            if stat.S_ISLNK(info.st_mode):
                if parents:
                    stats[parents[0]]["symlinks"] += 1
                relative = path.relative_to(parent)
                for name, prefix in prefixes:
                    if relative == prefix or prefix in relative.parents:
                        stats[name]["symlinks"] += 1
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            relative = path.relative_to(parent)
            names = list(parents)
            names.extend(
                name
                for name, prefix in prefixes
                if relative == prefix or prefix in relative.parents
            )
            for name in names:
                row = stats[name]
                row["regular_files"] += 1
                row["logical_bytes"] += info.st_size
                row["path_allocated_bytes"] += getattr(info, "st_blocks", 0) * 512
                if info.st_nlink > 1:
                    row["hard_link_paths"] += 1
                row["extensions"][path.suffix.lower() or "[none]"] += 1
                row["largest"].append((info.st_size, str(path)))

    for row in stats.values():
        row["extensions"] = [
            {"extension": ext, "files": count}
            for ext, count in row["extensions"].most_common(8)
        ]
        row["largest"] = [
            {"bytes": size, "path": path}
            for size, path in sorted(row["largest"], reverse=True)[:top]
        ]
    return stats


def inventory(repo: Path, cache: Path, top: int) -> dict[str, Any]:
    repo = repo.resolve()
    cache = cache.expanduser().resolve()
    worktrees = _worktrees(repo)
    root_specs = [
        ("data", repo / "data"),
        ("data/intake", repo / "data/intake"),
        ("data/operations", repo / "data/operations"),
        ("data/operations/pipeline", repo / "data/operations/pipeline"),
        ("data/operations/pipeline-nodes", repo / "data/operations/pipeline-nodes"),
        ("data/operations-recovery", repo / "data/operations-recovery"),
        (
            "data/operations-recovery/0108-m10-20261105",
            repo / "data/operations-recovery/0108-m10-20261105",
        ),
        ("data/models", repo / "data/models"),
        (".runtime", repo / ".runtime"),
        (".runtime/pipeline/derived-views", repo / ".runtime/pipeline/derived-views"),
        (".runtime/gemini-cache", repo / ".runtime/gemini-cache"),
        (
            ".runtime/rfdetr-segmentation-0092-m4",
            repo / ".runtime/rfdetr-segmentation-0092-m4",
        ),
        (
            ".runtime/synthetic-visible-region-0070-all-recordings-training-v2",
            repo / ".runtime/synthetic-visible-region-0070-all-recordings-training-v2",
        ),
        (
            ".runtime/synthetic-visible-region-0070-m4-50-50",
            repo / ".runtime/synthetic-visible-region-0070-m4-50-50",
        ),
        ("shared-hard-fixture-cache", cache),
    ]
    summaries: dict[str, Any] = {}
    for parent, names in (
        (repo / "data", [x for x in root_specs if x[1].is_relative_to(repo / "data")]),
        (
            repo / ".runtime",
            [x for x in root_specs if x[1].is_relative_to(repo / ".runtime")],
        ),
        (cache, [x for x in root_specs if x[1] == cache]),
    ):
        if parent.exists():
            summaries.update(_summaries(parent, names, top))

    worktree_sizes = []
    for record in worktrees:
        path = Path(str(record["worktree"]))
        if path.exists() and path != repo:
            worktree_sizes.append(
                {
                    "path": str(path),
                    "head": record.get("HEAD"),
                    "branch": record.get("branch"),
                    "detached": "detached" in record,
                    "locked": record.get("locked"),
                    "allocated_kib_du": _du_kib(path),
                    "summary": _summaries(path, [("worktree", path)], top)["worktree"],
                }
            )

    tracked = _command(repo, "git", "ls-files", "-z", "data", ".runtime").split("\0")
    tracked = [path for path in tracked if path]
    lfs = _command(repo, "git", "lfs", "ls-files").splitlines()
    common_git = Path(_command(repo, "git", "rev-parse", "--git-common-dir").strip())
    if not common_git.is_absolute():
        common_git = repo / common_git
    ignore_samples = [
        "data/operations/pipeline-nodes",
        "data/models",
        ".runtime",
        "data/operations-recovery",
    ]
    ignore_rows = []
    for sample in ignore_samples:
        result = subprocess.run(
            ["git", "check-ignore", "-v", sample],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
        )
        ignore_rows.append(
            {
                "path": sample,
                "ignored": result.returncode == 0,
                "rule": result.stdout.strip(),
            }
        )
    return {
        "schema_version": "0115-storage-inventory/v1",
        "repository": str(repo),
        "head": _command(repo, "git", "rev-parse", "HEAD").strip(),
        "roots": summaries,
        "registered_worktrees": worktrees,
        "other_worktree_summaries": worktree_sizes,
        "shared_git": {
            "path": str(common_git.resolve()),
            "allocated_kib_du": _du_kib(common_git),
            "count_objects": _command(repo, "git", "count-objects", "-vH")
            .strip()
            .splitlines(),
            "lfs_file_count": len(lfs),
        },
        "tracked_file_count_data_runtime": len(tracked),
        "tracked_file_counts_by_root": {
            "data/operations/pipeline": sum(
                p.startswith("data/operations/pipeline/") for p in tracked
            ),
            "other": sum(
                not p.startswith("data/operations/pipeline/") for p in tracked
            ),
        },
        "ignore_samples": ignore_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--cache", type=Path, default=Path.home() / ".cache/doko-detector"
    )
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()
    print(
        json.dumps(inventory(args.repo, args.cache, args.top), sort_keys=True, indent=2)
    )


if __name__ == "__main__":
    main()
