"""Small filesystem primitives shared by the backend stores.

These helpers handle path safety and publication mechanics only. They do not define a resource
schema or a repository abstraction. Each concrete store remains responsible for its own manifest,
state, and validation rules.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any


class FilesystemPathError(ValueError):
    """A path is not safely contained by its configured filesystem root."""


@dataclass(frozen=True, slots=True)
class DirectoryDiagnostic:
    """A concise reason why one root entry was not returned as a resource directory."""

    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class DirectoryEnumeration:
    """Deterministic directory entries and non-fatal validation diagnostics."""

    paths: tuple[Path, ...]
    diagnostics: tuple[DirectoryDiagnostic, ...]


def contained_path(root: Path, relative_path: str | Path) -> Path:
    """Resolve one safe relative path below ``root``.

    Existing symlinks are resolved before the containment check. This prevents a valid-looking
    path from escaping through a symlinked directory or file.
    """

    raw = str(relative_path)
    path = PurePath(relative_path)
    if (
        not raw
        or path.is_absolute()
        or raw in {".", ".."}
        or "\\" in raw
        or ".." in path.parts
    ):
        raise FilesystemPathError("path must be a non-empty safe relative path")

    resolved_root = Path(root).expanduser().resolve()
    resolved_path = (resolved_root / path).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as error:
        raise FilesystemPathError("path escapes its configured root") from error
    return resolved_path


@contextmanager
def staging_directory(root: Path, *, prefix: str = ".staging-") -> Iterator[Path]:
    """Create a private staging directory and remove it unless it was published."""

    resolved_root = Path(root).expanduser().resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    if not resolved_root.is_dir():
        raise OSError(f"filesystem root is not a directory: {resolved_root}")
    staging = Path(tempfile.mkdtemp(prefix=prefix, dir=resolved_root))
    try:
        yield staging
    finally:
        if staging.exists() or staging.is_symlink():
            shutil.rmtree(staging)


def commit_staged_directory(
    staging: Path,
    destination: Path,
    *,
    validate: Callable[[Path], object] | None = None,
) -> Path:
    """Validate and atomically publish a complete staging directory.

    The staging and destination parent must be the same directory. Files and directories are
    synced before one rename, and the parent directory is synced after publication. A caller can
    use :func:`staging_directory` to clean an unsuccessful publication.
    """

    staging = Path(staging)
    destination = Path(destination)
    if staging.is_symlink() or not staging.is_dir():
        raise OSError(f"staging path is not a directory: {staging}")

    parent = destination.parent.expanduser().resolve()
    if staging.parent.expanduser().resolve() != parent:
        raise FilesystemPathError("staging and destination must share one parent directory")
    parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)

    if validate is not None:
        validate(staging)
    _sync_tree(staging)
    os.rename(staging, destination)
    _sync_directory(parent)
    return destination


def atomic_write_json(
    path: Path,
    value: bytes | Mapping[str, Any] | list[Any],
    *,
    validate: Callable[[bytes], object] | None = None,
) -> bytes:
    """Validate and atomically replace one JSON document.

    Mapping and list values use deterministic compact JSON. Bytes are kept byte-for-byte, but
    still need to contain valid JSON. The existing target is untouched if validation, writing, or
    replacement fails before the atomic replacement.
    """

    payload = value if isinstance(value, bytes) else _canonical_json_bytes(value)
    try:
        json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("JSON document must be valid UTF-8 JSON") from error
    if validate is not None:
        validate(payload)

    target = Path(path).expanduser()
    parent = target.parent.resolve()
    if target.parent.absolute() != parent:
        raise FilesystemPathError("JSON document parent must not escape through a symlink")
    parent.mkdir(parents=True, exist_ok=True)
    safe_target = contained_path(parent, target.name)
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{safe_target.name}.",
            suffix=".tmp",
            dir=parent,
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, safe_target)
        temporary = None
        _sync_directory(parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return payload


# The longer name makes call sites explicit when they replace mutable state documents.
atomic_replace_json = atomic_write_json


def enumerate_resource_directories(
    root: Path,
    *,
    validate: Callable[[Path], object] | None = None,
    staging_prefixes: tuple[str, ...] = (".",),
) -> DirectoryEnumeration:
    """Return valid resource directories in stable order with concise diagnostics.

    The helper ignores staging and symlink entries. A supplied validator decides whether a
    directory is a complete resource. Validation failures are reported, not returned as valid
    entries, so a catalog can remain usable while exposing the local repair problem.
    """

    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        return DirectoryEnumeration(
            paths=(),
            diagnostics=(DirectoryDiagnostic(root, "resource root is unavailable"),),
        )

    paths: list[Path] = []
    diagnostics: list[DirectoryDiagnostic] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.name.startswith(staging_prefixes):
            diagnostics.append(DirectoryDiagnostic(path, "staging directory ignored"))
            continue
        if path.is_symlink():
            diagnostics.append(DirectoryDiagnostic(path, "symlink resource ignored"))
            continue
        if not path.is_dir():
            diagnostics.append(DirectoryDiagnostic(path, "non-directory resource ignored"))
            continue
        if validate is not None:
            try:
                validate(path)
            except (OSError, TypeError, UnicodeError, ValueError) as error:
                diagnostics.append(DirectoryDiagnostic(path, f"invalid resource: {error}"))
                continue
        paths.append(path)
    return DirectoryEnumeration(tuple(paths), tuple(diagnostics))


def _canonical_json_bytes(value: Mapping[str, Any] | list[Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sync_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            raise OSError(f"staging tree contains a symlink: {path}")
        if path.is_file():
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
        elif path.is_dir():
            _sync_directory(path)
    _sync_directory(root)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "DirectoryDiagnostic",
    "DirectoryEnumeration",
    "FilesystemPathError",
    "atomic_replace_json",
    "atomic_write_json",
    "commit_staged_directory",
    "contained_path",
    "enumerate_resource_directories",
    "staging_directory",
]
