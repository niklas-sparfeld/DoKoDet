"""Upload a shared evidence fixture to a local backend."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from dokodetector_backend.contract import EvidenceManifest, parse_manifest_bytes

SYNTHETIC_FRAME_PREFIX = b"DokoDetector local fixture frame: "


def prepare_fixture(
    fixture_directory: Path,
) -> tuple[bytes, EvidenceManifest, dict[str, bytes], bytes | None]:
    """Load a fixture and prepare its manifest and media bytes for upload.

    A fixture may contain exact files below ``frames``. The checked-in shared examples contain
    manifest data only, so this helper creates deterministic local frame bytes for those examples
    and updates only the transmitted frame length and digest fields.
    """

    manifest_path = fixture_directory / "manifest.json"
    original_bytes = manifest_path.read_bytes()
    payload = json.loads(original_bytes)
    manifest = parse_manifest_bytes(original_bytes)
    frame_sources: dict[str, bytes] = {}
    generated_payload = copy.deepcopy(payload)
    generated = False

    for frame, frame_payload in zip(manifest.frames, generated_payload["frames"], strict=True):
        frame_path = fixture_directory / "frames" / f"{frame.part_name}.jpg"
        if frame_path.is_file():
            frame_bytes = frame_path.read_bytes()
            if len(frame_bytes) != frame.byte_length or _sha256(frame_bytes) != frame.sha256:
                raise ValueError(f"Frame bytes do not match {frame.part_name}.")
        else:
            frame_bytes = SYNTHETIC_FRAME_PREFIX + frame.part_name.encode("ascii")
            frame_payload["byte_length"] = len(frame_bytes)
            frame_payload["sha256"] = _sha256(frame_bytes)
            generated = True
        frame_sources[frame.part_name] = frame_bytes

    manifest_bytes = (
        json.dumps(generated_payload, separators=(",", ":")).encode("utf-8")
        if generated
        else original_bytes
    )
    manifest = parse_manifest_bytes(manifest_bytes)
    video_source: bytes | None = None
    if manifest.video_snippet is not None and manifest.video_snippet.capture_complete:
        assert manifest.video_snippet.part_name is not None
        video_path = fixture_directory / "video" / f"{manifest.video_snippet.part_name}.mp4"
        if not video_path.is_file():
            video_path = fixture_directory / "snippet.mp4"
        video_source = video_path.read_bytes()
        if (
            len(video_source) != manifest.video_snippet.byte_length
            or _sha256(video_source) != manifest.video_snippet.sha256
        ):
            raise ValueError("Video snippet bytes do not match the manifest.")
    return manifest_bytes, manifest, frame_sources, video_source


def upload_fixture(
    fixture_directory: Path,
    server: str,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Upload one prepared fixture and return the JSON response."""

    manifest_bytes, manifest, frame_sources, video_source = prepare_fixture(fixture_directory)
    package_record, task_enrollment, lineage = _repository_documents(manifest)
    files: list[tuple[str, tuple[str, bytes, str]]] = [
        ("manifest", ("manifest.json", manifest_bytes, "application/json")),
        ("package_record", ("package-record.json", package_record, "application/json")),
        (
            "task_enrollment",
            ("initial-task-enrollment.json", task_enrollment, "application/json"),
        ),
        ("lineage", ("lineage.json", lineage, "application/json")),
    ]
    files.extend(
        (
            frame.part_name,
            (f"{frame.part_name}.jpg", frame_sources[frame.part_name], "image/jpeg"),
        )
        for frame in manifest.frames
    )
    if video_source is not None:
        assert manifest.video_snippet is not None
        assert manifest.video_snippet.part_name is not None
        files.append(
            (
                manifest.video_snippet.part_name,
                (f"{manifest.video_snippet.part_name}.mp4", video_source, "video/mp4"),
            )
        )

    url = f"{server.rstrip('/')}/v1/evidence-packages/{manifest.package_id}"
    with httpx.Client(timeout=timeout) as client:
        response = client.put(url, files=files)
    try:
        body = response.json()
    except ValueError as error:
        message = f"The server returned a non-JSON response ({response.status_code})."
        raise RuntimeError(message) from error
    if response.is_error:
        raise RuntimeError(f"The upload failed ({response.status_code}): {json.dumps(body)}")
    return body


def main(argv: list[str] | None = None) -> int:
    """Run the fixture upload command."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="Fixture directory with manifest.json")
    parser.add_argument(
        "--server",
        default="http://127.0.0.1:8000",
        help="Backend base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=30.0,
        help="HTTP timeout in seconds (default: 30)",
    )
    args = parser.parse_args(argv)

    try:
        body = upload_fixture(args.fixture, args.server, timeout=args.timeout)
    except (OSError, ValueError, httpx.HTTPError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(json.dumps(body, indent=2))
    return 0


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _repository_documents(manifest: EvidenceManifest) -> tuple[bytes, bytes, bytes]:
    """Create deterministic repository metadata for a local evidence fixture."""

    package_id = str(manifest.package_id)
    source_asset_id = f"source-evidence-{package_id}"
    package_record = {
        "schema_version": "evidence-package-record/v1",
        "package_id": package_id,
        "source_asset_id": source_asset_id,
        "source_permission": "project_use",
        "allowed_uses": ["evaluation"],
        "retention_state": "active",
        "notes": "Generated by the local evidence fixture uploader.",
    }
    task_enrollment = {
        "schema_version": "task-enrollment/v1",
        "source_asset_id": source_asset_id,
        "enrollments": [
            {
                "task_enrollment_id": f"enrollment-{package_id}-cardevent",
                "task": "cardevent_event_detection",
                "disposition": "selected",
                "lifecycle_state": "intake",
                "operator": "fixture-uploader",
                "created_at_utc": "2026-01-01T00:00:00Z",
                "reason": None,
            },
            {
                "task_enrollment_id": f"enrollment-{package_id}-table",
                "task": "table_evidence_analysis",
                "disposition": "selected",
                "lifecycle_state": "intake",
                "operator": "fixture-uploader",
                "created_at_utc": "2026-01-01T00:00:00Z",
                "reason": None,
            },
        ],
    }
    lineage = {
        "schema_version": "evidence-package-lineage/v1",
        "package_id": package_id,
        "parent_source_asset_id": None,
        "parent_recording_id": None,
        "parent_video_id": None,
        "session_id": str(manifest.session.session_id),
    }

    def encode(payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()

    return encode(package_record), encode(task_enrollment), encode(lineage)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "prepare_fixture", "upload_fixture"]
