"""Copy selected immutable operator recording bundles into isolated local storage."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from dokodetector_backend.config import Settings
from dokodetector_backend.intake_contract import parse_repository_bundle
from dokodetector_backend.recording_bundle_store import (
    RecordingBundleStore,
)
from dokodetector_backend.recording_folder_store import RecordingFolderStore
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
    target_store = RecordingFolderStore(Path(target_root).expanduser().resolve())
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
        created = target_store.get(recording_id) is None
        try:
            target_store.publish_bundle(source_path, recording_id=recording_id)
        except (OSError, ValueError, RuntimeError) as error:
            raise OperatorCorpusImportError(
                f"Could not copy operator corpus bundle {recording_id}: {error}"
            ) from error
        # The target is a recording folder, not a second copy of the intake transport bundle.
        target_recording = target_store.get(recording_id)
        if (
            target_recording is None
            or target_recording.source.get("sha256") != source.source_sha256
        ):
            raise OperatorCorpusImportError(
                f"Imported recording differs from the source: {recording_id}."
            )
        target_path = target_store.recording_path(recording_id)
        copied_media = target_path / target_recording.media["relative_path"]
        manifest = parse_repository_bundle((source_path / "manifest.json").read_bytes())
        source_media = source_path / manifest.files.video.relative_path
        if source_media.samefile(copied_media) or copied_media.stat().st_nlink != 1:
            raise OperatorCorpusImportError(
                f"Imported media is linked to shared content: {recording_id}."
            )
        for proposal in target_recording.proposal_generator_runs:
            copied_proposal = target_path / proposal["relative_path"]
            if copied_proposal.stat().st_nlink != 1:
                raise OperatorCorpusImportError(
                    f"Imported proposal input is linked to shared content: {recording_id}."
                )
        imported.append(
            ImportedBundle(
                recording_id=recording_id,
                bundle_fingerprint=source.bundle_fingerprint,
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
            settings.recordings_root,
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
