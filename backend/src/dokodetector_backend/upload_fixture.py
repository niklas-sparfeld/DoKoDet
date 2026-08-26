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
) -> tuple[bytes, EvidenceManifest, dict[str, bytes]]:
    """Load a fixture and prepare its manifest and frame bytes for upload.

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
    return manifest_bytes, manifest, frame_sources


def upload_fixture(
    fixture_directory: Path,
    server: str,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Upload one prepared fixture and return the JSON response."""

    manifest_bytes, manifest, frame_sources = prepare_fixture(fixture_directory)
    files: list[tuple[str, tuple[str, bytes, str]]] = [
        ("manifest", ("manifest.json", manifest_bytes, "application/json"))
    ]
    files.extend(
        (
            frame.part_name,
            (f"{frame.part_name}.jpg", frame_sources[frame.part_name], "image/jpeg"),
        )
        for frame in manifest.frames
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


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "prepare_fixture", "upload_fixture"]
