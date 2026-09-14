"""Migrate stored visible-card revisions to the current content contract."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from doko_operations.pipeline_data import (
    DataRevision,
    PipelineDataContractError,
    canonical_data_revision_bytes,
    canonical_json_bytes,
    sha256_bytes,
)
from table_evidence_analyzer.pipeline_data import (
    PipelineDataError,
    VisibleCardData,
    canonical_visible_card_data_bytes,
    parse_visible_card_data_bytes,
)

from dokodetector_backend.filesystem import atomic_replace_json


class VisibleCardDataMigrationError(RuntimeError):
    """A stored visible-card revision cannot be migrated safely."""


@dataclass(frozen=True, slots=True)
class VisibleCardDataMigrationReport:
    """The deterministic result of one visible-card revision migration pass."""

    revisions_scanned: int
    revisions_changed: int
    outcomes_added: int
    revisions_already_current: int
    changed_revision_ids: tuple[str, ...]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "revisions_scanned": self.revisions_scanned,
            "revisions_changed": self.revisions_changed,
            "outcomes_added": self.outcomes_added,
            "revisions_already_current": self.revisions_already_current,
            "changed_revision_ids": list(self.changed_revision_ids),
        }


@contextmanager
def _revision_lock(path: Path) -> Iterator[None]:
    """Serialize migration with the pipeline store's per-revision lock."""

    try:
        from fcntl import LOCK_EX, LOCK_UN, flock
    except ImportError:  # pragma: no cover - supported development hosts use macOS or Linux.
        yield
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        flock(handle.fileno(), LOCK_EX)
        try:
            yield
        finally:
            flock(handle.fileno(), LOCK_UN)


def _read_json(path: Path, context: str) -> tuple[bytes, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"{context} contains a non-finite JSON number: {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{context} contains a duplicate field: {key}")
            result[key] = value
        return result

    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise VisibleCardDataMigrationError(f"Could not read {context}: {path}") from error
    return raw, value


def _as_mapping(value: Any, context: str, path: Path) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VisibleCardDataMigrationError(f"{context} must be an object: {path}")
    return value


def _prepare_revision(
    revision_path: Path,
) -> tuple[DataRevision, bytes, bytes, int, bool]:
    manifest_path = revision_path / "manifest.json"
    content_path = revision_path / "content.json"
    if revision_path.is_symlink() or not revision_path.is_dir():
        raise VisibleCardDataMigrationError(f"revision directory is unavailable: {revision_path}")
    members = {member.name for member in revision_path.iterdir()}
    if members != {"manifest.json", "content.json"}:
        raise VisibleCardDataMigrationError(
            f"revision must contain only manifest.json and content.json: {revision_path}"
        )
    if manifest_path.is_symlink() or content_path.is_symlink():
        raise VisibleCardDataMigrationError(f"revision files must not be symlinks: {revision_path}")

    old_manifest_bytes, raw_manifest = _read_json(manifest_path, "revision manifest")
    manifest_mapping = _as_mapping(raw_manifest, "revision manifest", manifest_path)
    if manifest_mapping.get("content_type") != "visible_cards":
        raise VisibleCardDataMigrationError(
            f"visible-card migration received an unsupported content type: {revision_path}"
        )
    try:
        manifest = DataRevision.from_mapping(manifest_mapping)
    except (PipelineDataContractError, TypeError, ValueError) as error:
        raise VisibleCardDataMigrationError(
            f"Invalid revision manifest: {manifest_path}"
        ) from error
    if manifest.revision_id != revision_path.name:
        raise VisibleCardDataMigrationError(
            f"revision ID differs from its directory name: {revision_path}"
        )

    old_content_bytes, raw_content = _read_json(content_path, "visible-card content")
    content_mapping = dict(_as_mapping(raw_content, "visible-card content", content_path))
    raw_outcomes = content_mapping.get("outcomes")
    if not isinstance(raw_outcomes, list):
        raise VisibleCardDataMigrationError(
            f"visible-card content.outcomes must be a list: {content_path}"
        )

    outcomes_added = 0
    for index, raw_outcome in enumerate(raw_outcomes):
        if not isinstance(raw_outcome, Mapping):
            raise VisibleCardDataMigrationError(
                f"visible-card content.outcomes[{index}] must be an object: {content_path}"
            )
        if "ignored_regions" not in raw_outcome:
            raw_outcome["ignored_regions"] = []
            outcomes_added += 1

    try:
        content: VisibleCardData = parse_visible_card_data_bytes(
            canonical_json_bytes(content_mapping)
        )
    except (PipelineDataError, TypeError, ValueError) as error:
        raise VisibleCardDataMigrationError(
            f"Invalid visible-card content: {content_path}"
        ) from error
    content_bytes = canonical_visible_card_data_bytes(content)

    manifest_mapping = dict(manifest_mapping)
    manifest_mapping["content_sha256"] = sha256_bytes(content_bytes)
    try:
        migrated_manifest = DataRevision.from_mapping(manifest_mapping)
    except (PipelineDataContractError, TypeError, ValueError) as error:
        raise VisibleCardDataMigrationError(
            f"Invalid migrated revision manifest: {manifest_path}"
        ) from error
    manifest_bytes = canonical_data_revision_bytes(migrated_manifest)
    changed = old_content_bytes != content_bytes or old_manifest_bytes != manifest_bytes
    return migrated_manifest, manifest_bytes, content_bytes, outcomes_added, changed


def _validate_written_revision(
    revision_path: Path,
    manifest_bytes: bytes,
    content_bytes: bytes,
) -> None:
    manifest_path = revision_path / "manifest.json"
    content_path = revision_path / "content.json"
    actual_manifest = manifest_path.read_bytes()
    actual_content = content_path.read_bytes()
    if actual_manifest != manifest_bytes or actual_content != content_bytes:
        raise VisibleCardDataMigrationError(
            f"revision changed while it was being migrated: {revision_path}"
        )
    try:
        manifest = DataRevision.from_mapping(json.loads(actual_manifest.decode("utf-8")))
        content = parse_visible_card_data_bytes(actual_content)
    except (PipelineDataContractError, PipelineDataError, TypeError, ValueError) as error:
        raise VisibleCardDataMigrationError(
            f"Migrated revision failed validation: {revision_path}"
        ) from error
    if manifest.content_type != "visible_cards":
        raise VisibleCardDataMigrationError(
            f"Migrated revision has the wrong type: {revision_path}"
        )
    if sha256_bytes(canonical_visible_card_data_bytes(content)) != manifest.content_sha256:
        raise VisibleCardDataMigrationError(
            f"Migrated revision digest does not match: {revision_path}"
        )
    if canonical_data_revision_bytes(manifest) != actual_manifest:
        raise VisibleCardDataMigrationError(f"Migrated manifest is not canonical: {manifest_path}")
    if canonical_visible_card_data_bytes(content) != actual_content:
        raise VisibleCardDataMigrationError(f"Migrated content is not canonical: {content_path}")


def migrate_visible_card_revisions(
    revisions_root: Path | str,
    *,
    apply: bool = True,
) -> VisibleCardDataMigrationReport:
    """Add empty ignore-region lists to every old visible-card outcome.

    The migration updates the content digest in each affected manifest. It is safe to rerun.
    When ``apply`` is false, the pass validates and reports changes without writing them.
    """

    root = Path(revisions_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise VisibleCardDataMigrationError(f"revision root is unavailable: {root}")

    revisions_scanned = 0
    revisions_changed = 0
    outcomes_added = 0
    revisions_already_current = 0
    changed_revision_ids: list[str] = []

    for revision_path in sorted(root.iterdir(), key=lambda path: path.name):
        if (
            not revision_path.is_dir()
            or revision_path.is_symlink()
            or revision_path.name.startswith(".")
        ):
            continue
        manifest_path = revision_path / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            continue
        _, raw_manifest = _read_json(manifest_path, "revision manifest")
        if (
            not isinstance(raw_manifest, Mapping)
            or raw_manifest.get("content_type") != "visible_cards"
        ):
            continue

        revisions_scanned += 1
        lock_path = root / f".{revision_path.name}.lock"
        with _revision_lock(lock_path):
            manifest, manifest_bytes, content_bytes, added, changed = _prepare_revision(
                revision_path
            )
            outcomes_added += added
            if not changed:
                revisions_already_current += 1
                continue
            revisions_changed += 1
            changed_revision_ids.append(manifest.revision_id)
            if not apply:
                continue
            content_path = revision_path / "content.json"
            manifest_path = revision_path / "manifest.json"
            atomic_replace_json(content_path, content_bytes)
            atomic_replace_json(manifest_path, manifest_bytes)
            _validate_written_revision(revision_path, manifest_bytes, content_bytes)

    return VisibleCardDataMigrationReport(
        revisions_scanned=revisions_scanned,
        revisions_changed=revisions_changed,
        outcomes_added=outcomes_added,
        revisions_already_current=revisions_already_current,
        changed_revision_ids=tuple(changed_revision_ids),
    )


def _default_repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repository_root = _default_repository_root()
    parser.add_argument("--repository-root", type=Path, default=repository_root)
    parser.add_argument("--revisions-root", type=Path, default=None)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate and report required changes without modifying data.",
    )
    args = parser.parse_args(argv)
    revisions_root = args.revisions_root or args.repository_root / (
        "data/operations/pipeline/revisions"
    )
    report = migrate_visible_card_revisions(revisions_root, apply=not args.check)
    print(json.dumps(report.to_mapping(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "VisibleCardDataMigrationError",
    "VisibleCardDataMigrationReport",
    "main",
    "migrate_visible_card_revisions",
]
