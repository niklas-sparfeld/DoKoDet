"""Adapt an accepted evidence package to the analyzer runtime boundary."""

from __future__ import annotations

import hashlib
from pathlib import Path

from table_evidence_analyzer import AnalyzerEvidence, AnalyzerFrame

from dokodetector_backend.contract import (
    EvidenceManifest,
    FrameManifest,
    parse_manifest_bytes,
)
from dokodetector_backend.evidence_package_storage import (
    EvidencePackageStorage,
    calculate_bundle_fingerprint,
)
from dokodetector_backend.repository import StoredFrame, StoredPackage


class EvidenceIntegrityError(RuntimeError):
    """Stored evidence does not match its accepted database metadata."""


def load_analyzer_evidence(
    package: StoredPackage, storage: EvidencePackageStorage
) -> AnalyzerEvidence:
    """Verify one accepted package and expose only its visual evidence."""

    if package.state != "stored":
        raise EvidenceIntegrityError("The evidence package is not in the stored state.")

    manifest_path = storage.package_path(package.package_id) / "evidence-manifest.json"
    manifest_bytes = _read_file(manifest_path, "The stored manifest could not be read.")
    expected_manifest_bytes = package.manifest_json.encode("utf-8")
    if manifest_bytes != expected_manifest_bytes:
        raise EvidenceIntegrityError("The stored manifest does not match the database row.")
    if _sha256(manifest_bytes) != package.manifest_sha256:
        raise EvidenceIntegrityError("The stored manifest hash does not match the database row.")

    try:
        manifest = parse_manifest_bytes(manifest_bytes)
    except (TypeError, ValueError) as error:
        raise EvidenceIntegrityError("The stored manifest failed validation.") from error
    try:
        package_files = storage.file_digests(package.package_id)
    except OSError as error:
        raise EvidenceIntegrityError("The stored package files could not be read.") from error
    if calculate_bundle_fingerprint(package_files) != package.package_fingerprint:
        raise EvidenceIntegrityError("The stored package fingerprint does not match its files.")
    _verify_package_metadata(package, manifest)

    manifest_frames = {frame.part_name: frame for frame in manifest.frames}
    stored_frames = {frame.part_name: frame for frame in package.frames}
    if set(manifest_frames) != set(stored_frames):
        raise EvidenceIntegrityError("The stored frame rows do not match the manifest.")

    frames: list[AnalyzerFrame] = []
    for frame in manifest.frames:
        stored_frame = stored_frames[frame.part_name]
        _verify_frame_metadata(frame, stored_frame)
        frame_path = _safe_path(
            storage.package_path(package.package_id), stored_frame.relative_path
        )
        frame_bytes = _read_file(frame_path, "A stored frame could not be read.")
        if (
            len(frame_bytes) != stored_frame.byte_length
            or _sha256(frame_bytes) != stored_frame.sha256
        ):
            raise EvidenceIntegrityError("A stored frame hash does not match the database row.")
        frames.append(
            AnalyzerFrame(
                part_name=frame.part_name,
                actual_offset_ms=frame.actual_offset_ms,
                width=frame.width,
                height=frame.height,
                local_reference=str(frame_path),
            )
        )

    try:
        return AnalyzerEvidence(
            package_id=package.package_id,
            event_time_ms=manifest.event.event_time_ms,
            frames=frames,
        )
    except ValueError as error:
        raise EvidenceIntegrityError(
            "The stored evidence cannot be used by the analyzer."
        ) from error


def _verify_package_metadata(
    package: StoredPackage,
    manifest: EvidenceManifest,
) -> None:
    if (
        manifest.package_id != package.package_id
        or manifest.schema_version != package.schema_version
        or manifest.session.session_id != package.session_id
        or manifest.session.event_sequence != package.event_sequence
        or manifest.event.event_time_ms != package.event_time_ms
    ):
        raise EvidenceIntegrityError("The stored package row does not match the manifest.")


def _verify_frame_metadata(
    frame: FrameManifest,
    stored_frame: StoredFrame,
) -> None:
    expected_path = f"frames/{frame.part_name}.jpg"
    if (
        stored_frame.part_name != frame.part_name
        or stored_frame.target_offset_ms != frame.target_offset_ms
        or stored_frame.actual_offset_ms != frame.actual_offset_ms
        or stored_frame.session_elapsed_ms != frame.session_elapsed_ms
        or stored_frame.captured_at_utc != frame.captured_at_utc
        or stored_frame.content_type != frame.content_type
        or stored_frame.byte_length != frame.byte_length
        or stored_frame.sha256 != frame.sha256
        or stored_frame.relative_path != expected_path
    ):
        raise EvidenceIntegrityError("The stored frame row does not match the manifest.")


def _safe_path(root_path: Path, relative_path: str) -> Path:
    root = root_path.resolve()
    path = (root_path / relative_path).resolve()
    if root not in path.parents:
        raise EvidenceIntegrityError("A stored file path escapes the evidence root.")
    return path


def _read_file(path: Path, message: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise EvidenceIntegrityError(message) from error


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


__all__ = ["EvidenceIntegrityError", "load_analyzer_evidence"]
