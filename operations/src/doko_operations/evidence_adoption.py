"""One-time adoption of legacy runtime evidence into repository intake."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from .evidence_package import load_evidence_package
from .intake_contract import (
    parse_evidence_package_lineage,
    parse_evidence_package_record,
)


class EvidencePackageAdoptionError(ValueError):
    """The legacy package cannot be adopted without operator metadata."""


def adopt_runtime_evidence_package(
    runtime_root: str | Path,
    package_id: str,
    metadata_path: str | Path,
    *,
    evidence_package_root: str | Path,
) -> dict[str, Any]:
    """Copy one legacy runtime package into canonical repository intake.

    The command does not remove the runtime package.  The operator can remove that obsolete
    authority after the returned bundle has passed status and validation checks.
    """

    try:
        package_uuid = UUID(package_id)
    except (TypeError, ValueError) as error:
        raise EvidencePackageAdoptionError("package_id must be a UUID") from error
    legacy_path = Path(runtime_root).expanduser().resolve() / "evidence" / str(package_uuid)
    if not legacy_path.is_dir():
        raise EvidencePackageAdoptionError(f"legacy evidence package does not exist: {legacy_path}")
    manifest_bytes = (legacy_path / "manifest.json").read_bytes()
    manifest = _json_object(manifest_bytes, "legacy evidence manifest")
    if manifest.get("package_id") != str(package_uuid):
        raise EvidencePackageAdoptionError(
            "legacy evidence manifest package_id differs from argument"
        )
    metadata = _metadata_documents(Path(metadata_path).expanduser().resolve())
    record = parse_evidence_package_record(metadata["package-record.json"])
    lineage = parse_evidence_package_lineage(metadata["lineage.json"])
    if record.package_id != str(package_uuid) or lineage.package_id != str(package_uuid):
        raise EvidencePackageAdoptionError("adoption metadata package_id differs from argument")

    frames = manifest.get("frames")
    if not isinstance(frames, list):
        raise EvidencePackageAdoptionError("legacy evidence manifest frames must be a list")
    members: dict[str, bytes] = {
        "evidence-manifest.json": manifest_bytes,
        **metadata,
    }
    frame_descriptors: list[dict[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, Mapping) or not isinstance(frame.get("part_name"), str):
            raise EvidencePackageAdoptionError("legacy evidence manifest contains an invalid frame")
        part_name = frame["part_name"]
        frame_bytes = (legacy_path / "frames" / f"{part_name}.jpg").read_bytes()
        relative_path = f"frames/{part_name}.jpg"
        members[relative_path] = frame_bytes
        frame_descriptors.append(_descriptor(relative_path, "image/jpeg", frame_bytes))

    video_descriptor = None
    snippet = manifest.get("video_snippet")
    if isinstance(snippet, Mapping) and snippet.get("capture_complete"):
        part_name = snippet.get("part_name")
        if not isinstance(part_name, str):
            raise EvidencePackageAdoptionError("legacy evidence video snippet has no part name")
        video_path = legacy_path / "video" / f"{part_name}.mp4"
        if not video_path.is_file():
            video_path = legacy_path / "snippet.mp4"
        video_bytes = video_path.read_bytes()
        relative_path = f"video/{part_name}.mp4"
        members[relative_path] = video_bytes
        video_descriptor = _descriptor(relative_path, "video/mp4", video_bytes)

    bundle_payload = {
        "schema_version": "evidence-package-bundle/v1",
        "package_id": str(package_uuid),
        "source_asset_id": record.source_asset_id,
        "state": "complete",
        "files": {
            "evidence_manifest": _descriptor(
                "evidence-manifest.json", "application/json", manifest_bytes
            ),
            "package_record": _descriptor(
                "package-record.json", "application/json", metadata["package-record.json"]
            ),
            "task_enrollment": _descriptor(
                "initial-task-enrollment.json",
                "application/json",
                metadata["initial-task-enrollment.json"],
            ),
            "lineage": _descriptor("lineage.json", "application/json", metadata["lineage.json"]),
            "frames": frame_descriptors,
            "video_snippet": video_descriptor,
        },
    }
    members["manifest.json"] = _encode(bundle_payload)
    destination_root = Path(evidence_package_root).expanduser().resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / str(package_uuid)
    if destination.exists():
        try:
            load_evidence_package(destination)
        except (OSError, ValueError) as error:
            raise EvidencePackageAdoptionError(
                f"canonical package already exists but is invalid: {destination}"
            ) from error
        return {
            "package_id": str(package_uuid),
            "state": "already_adopted",
            "path": str(destination),
        }

    temporary = Path(tempfile.mkdtemp(prefix=f".{package_uuid}.", dir=destination_root))
    published = False
    try:
        for relative_path, value in members.items():
            target = temporary / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
        os.replace(temporary, destination)
        published = True
        load_evidence_package(destination)
    except (OSError, ValueError) as error:
        if published:
            shutil.rmtree(destination, ignore_errors=True)
        else:
            shutil.rmtree(temporary, ignore_errors=True)
        raise EvidencePackageAdoptionError(f"adopted package failed validation: {error}") from error
    return {"package_id": str(package_uuid), "state": "adopted", "path": str(destination)}


def _metadata_documents(path: Path) -> dict[str, bytes]:
    if path.is_dir():
        sources = {
            "package_record": path / "package-record.json",
            "task_enrollment": path / "initial-task-enrollment.json",
            "lineage": path / "lineage.json",
        }
        return {
            "package-record.json": sources["package_record"].read_bytes(),
            "initial-task-enrollment.json": sources["task_enrollment"].read_bytes(),
            "lineage.json": sources["lineage"].read_bytes(),
        }
    payload = _json_object(path.read_bytes(), "adoption metadata")
    keys = {"package_record", "task_enrollment", "lineage"}
    if set(payload) != keys:
        raise EvidencePackageAdoptionError(
            "adoption metadata must contain package_record, task_enrollment, and lineage"
        )
    names = {
        "package_record": "package-record.json",
        "task_enrollment": "initial-task-enrollment.json",
        "lineage": "lineage.json",
    }
    result: dict[str, bytes] = {}
    for key, name in names.items():
        value = payload[key]
        if not isinstance(value, Mapping):
            raise EvidencePackageAdoptionError(f"adoption metadata {key} must be an object")
        result[name] = _encode(value)
    return result


def _descriptor(relative_path: str, media_type: str, value: bytes) -> dict[str, Any]:
    return {
        "relative_path": relative_path,
        "type": media_type,
        "byte_length": len(value),
        "sha256": hashlib.sha256(value).hexdigest(),
    }


def _json_object(value: bytes, context: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidencePackageAdoptionError(f"{context} must be UTF-8 JSON") from error
    if not isinstance(payload, Mapping):
        raise EvidencePackageAdoptionError(f"{context} must be an object")
    return payload


def _encode(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


__all__ = ["EvidencePackageAdoptionError", "adopt_runtime_evidence_package"]
