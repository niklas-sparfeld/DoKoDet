"""Consolidate legacy and misplaced durable storage into central data roots."""

from __future__ import annotations

import argparse
import filecmp
import shutil
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

LEGACY_STORAGE_PATHS = (
    (Path("backend/data/incoming"), Path("data/incoming")),
    (Path("backend/data/intake"), Path("data/intake")),
    (Path("backend/data/operations"), Path("data/operations")),
    (Path("backend/data/outputs"), Path("data/outputs")),
    # The former backend-local root contained both durable records and cache files. Move only
    # durable resource families into the central operations root.
    (Path("backend/.runtime/pipeline/revisions"), Path("data/operations/pipeline/revisions")),
    (Path("backend/.runtime/pipeline/runs"), Path("data/operations/pipeline/runs")),
    (Path("backend/.runtime/pipeline/selections"), Path("data/operations/pipeline/selections")),
    (Path("backend/.runtime/table-observations"), Path("data/operations/table-observations")),
    (Path("backend/.runtime/round-analyses"), Path("data/operations/round-analyses")),
    # The repository runtime used these locations before durable records were separated.
    (Path(".runtime/pipeline/revisions"), Path("data/operations/pipeline/revisions")),
    (Path(".runtime/pipeline/runs"), Path("data/operations/pipeline/runs")),
    (Path(".runtime/pipeline/selections"), Path("data/operations/pipeline/selections")),
    (Path(".runtime/table-observations"), Path("data/operations/table-observations")),
    (Path(".runtime/round-analyses"), Path("data/operations/round-analyses")),
)
_IGNORED_FILE_NAMES = {
    ".DS_Store",
    "dokodetector.db",
    "dokodetector.db-shm",
    "dokodetector.db-wal",
}


class StorageConsolidationError(RuntimeError):
    """Legacy and central storage cannot be merged safely."""


@dataclass(frozen=True, slots=True)
class StorageConsolidationReport:
    """The files moved and deduplicated by one consolidation plan."""

    moved: tuple[str, ...]
    deduplicated: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.moved or self.deduplicated)


@dataclass(frozen=True, slots=True)
class _FileMove:
    source: Path
    destination: Path
    relative_path: str


def _file_moves(repository_root: Path) -> tuple[_FileMove, ...]:
    moves: list[_FileMove] = []
    for legacy_relative, central_relative in LEGACY_STORAGE_PATHS:
        source_root = (repository_root / legacy_relative).resolve()
        if not source_root.is_dir():
            continue
        destination_root = (repository_root / central_relative).resolve()
        for source in sorted(
            path
            for path in source_root.rglob("*")
            if path.is_file()
            and path.name not in _IGNORED_FILE_NAMES
            and not path.name.endswith(".lock")
        ):
            relative_path = source.relative_to(source_root)
            moves.append(
                _FileMove(
                    source=source,
                    destination=destination_root / relative_path,
                    relative_path=(central_relative / relative_path).as_posix(),
                )
            )
    return tuple(moves)


def _validate_moves(moves: Iterable[_FileMove]) -> tuple[list[_FileMove], list[_FileMove]]:
    moved: list[_FileMove] = []
    deduplicated: list[_FileMove] = []
    for move in moves:
        destination = move.destination
        if not destination.exists() and not destination.is_symlink():
            moved.append(move)
            continue
        if destination.is_file() and filecmp.cmp(move.source, destination, shallow=False):
            deduplicated.append(move)
            continue
        raise StorageConsolidationError(
            f"cannot consolidate {move.relative_path}: central data already differs"
        )
    return moved, deduplicated


def consolidate_storage(
    repository_root: Path | str,
    *,
    apply: bool,
) -> StorageConsolidationReport:
    """Plan or apply a merge from ``backend`` storage into repository storage."""

    root = Path(repository_root).expanduser().resolve()
    moves = _file_moves(root)
    moved, deduplicated = _validate_moves(moves)
    if not apply:
        return StorageConsolidationReport(
            moved=tuple(move.relative_path for move in moved),
            deduplicated=tuple(move.relative_path for move in deduplicated),
        )

    for move in (*moved, *deduplicated):
        if move in deduplicated:
            move.source.unlink()
            continue
        move.destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            move.source.rename(move.destination)
        except OSError:
            shutil.copy2(move.source, move.destination)
            move.source.unlink()

    for legacy_relative, _central_relative in LEGACY_STORAGE_PATHS:
        source_root = root / legacy_relative
        if source_root.is_dir():
            for directory in sorted(
                (path for path in source_root.rglob("*") if path.is_dir()),
                key=lambda path: len(path.parts),
                reverse=True,
            ):
                with suppress(OSError):
                    directory.rmdir()
    return StorageConsolidationReport(
        moved=tuple(move.relative_path for move in moved),
        deduplicated=tuple(move.relative_path for move in deduplicated),
    )


def main(argv: list[str] | None = None) -> int:
    """Consolidate legacy backend data into repository-level storage."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Move data after the complete plan passes conflict checks.",
    )
    args = parser.parse_args(argv)
    try:
        report = consolidate_storage(args.repository_root, apply=args.apply)
    except (OSError, StorageConsolidationError) as error:
        parser.error(str(error))
    action = "moved" if args.apply else "would move"
    print(f"{action} {len(report.moved)} files; deduplicated {len(report.deduplicated)} files")
    return 0


__all__ = [
    "LEGACY_STORAGE_PATHS",
    "StorageConsolidationError",
    "StorageConsolidationReport",
    "consolidate_storage",
    "main",
]
