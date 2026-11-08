"""Copy selected immutable operator recording bundles into isolated local storage."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from dokodetector_backend.config import Settings
from dokodetector_backend.recording_bundle_store import (
    RecordingBundleStore,
    RecordingBundleStoreError,
)
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage


class OperatorCorpusImportError(RuntimeError):
    """The selected operator recording could not be copied safely."""


@dataclass(frozen=True, slots=True)
class ImportedBundle:
    """Identity receipt for one bundle copied into worktree storage."""

    recording_id: str
    bundle_fingerprint: str
    file_count: int
    byte_length: int
    created: bool


def import_recordings(
    operator_corpus_root: Path | str,
    target_root: Path | str,
    recording_ids: tuple[str, ...],
) -> tuple[ImportedBundle, ...]:
    """Validate and byte-copy selected bundles from a read-only corpus into local storage."""

    source_storage = RepositoryBundleStorage(Path(operator_corpus_root).expanduser().resolve())
    source_store = RecordingBundleStore(source_storage)
    target_storage = RepositoryBundleStorage(Path(target_root).expanduser().resolve())
    target_store = RecordingBundleStore(target_storage)
    imported: list[ImportedBundle] = []

    if not recording_ids:
        raise OperatorCorpusImportError("Select at least one recording ID to import.")
    if len(set(recording_ids)) != len(recording_ids):
        raise OperatorCorpusImportError("Recording IDs must be unique.")

    for recording_id in recording_ids:
        source_path = source_storage.bundle_path(recording_id)
        if source_path.is_symlink() or not source_path.is_dir():
            raise OperatorCorpusImportError(
                f"Operator corpus bundle is missing or unsafe: {recording_id}."
            )
        source = source_store.get(recording_id)
        if source is None:
            raise OperatorCorpusImportError(
                f"Operator corpus bundle failed validation: {recording_id}."
            )
        source_files = source_storage.file_digests(recording_id)
        byte_length = sum(item.byte_length for item in source_files.values())
        try:
            with target_storage.start_bundle(recording_id) as staged:
                staged_files = {}
                for relative_path in sorted(source_files):
                    source_file = source_path / relative_path
                    with source_file.open("rb") as handle:
                        staged_files[relative_path] = staged.write_part(relative_path, handle)
                if staged_files != source_files:
                    raise OperatorCorpusImportError(
                        f"Copied file identity differs from source bundle: {recording_id}."
                    )
                stored, created = target_store.publish(staged, staged_files=staged_files)
        except (OSError, ValueError, RecordingBundleStoreError) as error:
            if isinstance(error, OperatorCorpusImportError):
                raise
            raise OperatorCorpusImportError(
                f"Could not copy operator corpus bundle {recording_id}: {error}"
            ) from error
        if stored.bundle_fingerprint != source.bundle_fingerprint:
            raise OperatorCorpusImportError(
                f"Imported bundle identity differs from the source: {recording_id}."
            )
        for relative_path in source_files:
            source_file = source_path / relative_path
            target_file = target_storage.bundle_path(recording_id) / relative_path
            if source_file.samefile(target_file) or target_file.stat().st_nlink != 1:
                raise OperatorCorpusImportError(
                    f"Imported file is linked to shared content: {recording_id}/{relative_path}."
                )
        imported.append(
            ImportedBundle(
                recording_id=recording_id,
                bundle_fingerprint=stored.bundle_fingerprint,
                file_count=len(source_files),
                byte_length=byte_length,
                created=created,
            )
        )
    return tuple(imported)


def main(argv: list[str] | None = None) -> int:
    """Copy selected validated operator bundles to ``DOKO_STORAGE_ROOT``."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-corpus-root", type=Path, required=True)
    parser.add_argument("--recording-id", action="append", required=True)
    args = parser.parse_args(argv)
    settings = Settings()
    if settings.storage_root is None:
        parser.error("set DOKO_STORAGE_ROOT to an isolated worktree storage directory")
    try:
        imported = import_recordings(
            args.operator_corpus_root,
            settings.repository_intake_root,
            tuple(args.recording_id),
        )
    except (OSError, ValueError, OperatorCorpusImportError) as error:
        parser.error(str(error))
    for item in imported:
        action = "copied" if item.created else "already present"
        print(
            f"{action} {item.recording_id}: {item.file_count} files, {item.byte_length} bytes, "
            f"bundle {item.bundle_fingerprint}"
        )
    return 0


__all__ = ["ImportedBundle", "OperatorCorpusImportError", "import_recordings", "main"]
