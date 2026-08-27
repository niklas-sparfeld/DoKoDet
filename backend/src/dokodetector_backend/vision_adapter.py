"""Adapt an accepted evidence package to the visual-only detector boundary."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from vision_detector import VisionEvidence, VisionFrame

from dokodetector_backend.contract import (
    EvidenceManifest,
    FrameManifest,
    calculate_package_fingerprint,
    parse_manifest_bytes,
)
from dokodetector_backend.repository import StoredFrame, StoredPackage
from dokodetector_backend.storage import EvidenceStorage


class EvidenceIntegrityError(RuntimeError):
    """Stored evidence does not match its accepted database metadata."""


def load_vision_evidence(package: StoredPackage, storage: EvidenceStorage) -> VisionEvidence:
    """Verify one accepted package and expose only its visual evidence."""

    if package.state != "stored":
        raise EvidenceIntegrityError("The evidence package is not in the stored state.")

    manifest_path = storage.package_path(package.package_id) / "manifest.json"
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
    _verify_package_metadata(package, manifest, manifest_bytes)

    manifest_frames = {frame.part_name: frame for frame in manifest.frames}
    stored_frames = {frame.part_name: frame for frame in package.frames}
    if set(manifest_frames) != set(stored_frames):
        raise EvidenceIntegrityError("The stored frame rows do not match the manifest.")

    frames: list[VisionFrame] = []
    for frame in manifest.frames:
        stored_frame = stored_frames[frame.part_name]
        _verify_frame_metadata(frame, stored_frame, package.package_id)
        frame_path = _safe_path(storage, stored_frame.relative_path)
        frame_bytes = _read_file(frame_path, "A stored frame could not be read.")
        if (
            len(frame_bytes) != stored_frame.byte_length
            or _sha256(frame_bytes) != stored_frame.sha256
        ):
            raise EvidenceIntegrityError("A stored frame hash does not match the database row.")
        frames.append(
            VisionFrame(
                part_name=frame.part_name,
                actual_offset_ms=frame.actual_offset_ms,
                width=frame.width,
                height=frame.height,
                local_reference=str(frame_path),
            )
        )

    try:
        return VisionEvidence(
            package_id=package.package_id,
            event_time_ms=manifest.event.event_time_ms,
            frames=frames,
        )
    except ValueError as error:
        raise EvidenceIntegrityError(
            "The stored evidence cannot be used by the detector."
        ) from error


def _verify_package_metadata(
    package: StoredPackage,
    manifest: EvidenceManifest,
    manifest_bytes: bytes,
) -> None:
    if (
        manifest.package_id != package.package_id
        or manifest.schema_version != package.schema_version
        or manifest.session.session_id != package.session_id
        or manifest.session.event_sequence != package.event_sequence
        or manifest.event.event_time_ms != package.event_time_ms
    ):
        raise EvidenceIntegrityError("The stored package row does not match the manifest.")
    if (
        calculate_package_fingerprint(
            manifest_bytes,
            manifest.frames,
            video_snippet=manifest.video_snippet,
        )
        != package.package_fingerprint
    ):
        raise EvidenceIntegrityError("The stored package fingerprint does not match the manifest.")


def _verify_frame_metadata(
    frame: FrameManifest,
    stored_frame: StoredFrame,
    package_id: UUID,
) -> None:
    expected_path = f"evidence/{package_id}/frames/{frame.part_name}.jpg"
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


def _safe_path(storage: EvidenceStorage, relative_path: str) -> Path:
    root = storage.root.resolve()
    path = (storage.root / relative_path).resolve()
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


__all__ = ["EvidenceIntegrityError", "load_vision_evidence"]
