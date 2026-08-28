"""Read CardEventNet inputs directly from shared repository-intake bundles."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .intake_contract import (
    ProposalGeneratorRun,
    RepositoryBundle,
    SourceRecord,
    TaskEnrollmentDocument,
    parse_json_bytes,
    validate_repository_bundle,
)


class RepositoryIntakeError(ValueError):
    """A repository-intake bundle is missing or invalid."""


@dataclass(frozen=True, slots=True)
class RepositoryRecording:
    """Validated paths and contracts for one canonical repository bundle."""

    root: Path
    bundle: RepositoryBundle
    source_record: SourceRecord
    task_enrollment: TaskEnrollmentDocument
    proposal_runs: tuple[ProposalGeneratorRun, ...]
    video_path: Path
    proposal_paths: tuple[Path, ...]


def load_repository_recording(path: str | Path) -> RepositoryRecording:
    """Validate and open one recording without copying any member file."""

    root = Path(path).expanduser()
    if not root.is_dir():
        raise RepositoryIntakeError(f"Repository bundle does not exist: {root}")
    try:
        manifest_bytes = (root / "manifest.json").read_bytes()
        source_bytes = (root / "source-record.json").read_bytes()
        enrollment_bytes = (root / "initial-task-enrollment.json").read_bytes()
        manifest = RepositoryBundle.from_mapping(parse_json_bytes(manifest_bytes, "manifest"))
        proposal_paths = tuple(
            root / descriptor.relative_path for descriptor in manifest.files.proposal_generator_runs
        )
        proposal_bytes = {
            descriptor.proposal_generator_run_id: proposal_path.read_bytes()
            for descriptor, proposal_path in zip(
                manifest.files.proposal_generator_runs, proposal_paths, strict=True
            )
        }
        bundle, source, enrollment, runs = validate_repository_bundle(
            parse_json_bytes(manifest_bytes, "manifest"),
            parse_json_bytes(source_bytes, "source record"),
            parse_json_bytes(enrollment_bytes, "task enrollment"),
            {
                key: parse_json_bytes(value, f"proposal {key}")
                for key, value in proposal_bytes.items()
            },
        )
        video_path = root / bundle.files.video.relative_path
        _verify_member(video_path, bundle.files.video.byte_length, bundle.files.video.sha256)
        for descriptor, proposal_path in zip(
            bundle.files.proposal_generator_runs, proposal_paths, strict=True
        ):
            _verify_member(proposal_path, descriptor.byte_length, descriptor.sha256)
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise RepositoryIntakeError(f"Repository bundle is invalid: {root}: {error}") from error
    return RepositoryRecording(root, bundle, source, enrollment, runs, video_path, proposal_paths)


def discover_repository_recordings(root: str | Path) -> tuple[RepositoryRecording, ...]:
    """Discover complete recording directories in deterministic order."""

    base = Path(root).expanduser()
    if not base.is_dir():
        return ()
    return tuple(
        load_repository_recording(path) for path in sorted(base.iterdir()) if path.is_dir()
    )


def _verify_member(path: Path, byte_length: int, expected_sha256: str) -> None:
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            length += len(chunk)
            digest.update(chunk)
    if length != byte_length or digest.hexdigest() != expected_sha256:
        raise RepositoryIntakeError(f"Repository member does not match its manifest: {path}")


__all__ = [
    "RepositoryIntakeError",
    "RepositoryRecording",
    "discover_repository_recordings",
    "load_repository_recording",
]
