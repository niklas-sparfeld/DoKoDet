#!/usr/bin/env python3
"""Verify the exact source videos used by the 0086 M5 identity handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "docs/reports/0086-M5_DINO_Campaign_Handoff.json"
SOURCE_ROOT = ROOT / "data/intake/recordings"
OUTPUT_DEFAULT = Path("docs/reports/0088-M1_Source_Verification.json")


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    args = parser.parse_args()

    handoff = json.loads(HANDOFF.read_text(encoding="utf-8"))
    recordings = []
    failures = []
    for entry in handoff["recordings"]:
        recording_id = entry["recording_id"]
        source_dir = SOURCE_ROOT / recording_id
        manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
        source_record = json.loads((source_dir / "source-record.json").read_text(encoding="utf-8"))
        video_entry = manifest["files"]["video"]
        video_path = (source_dir / video_entry["relative_path"]).resolve()
        if not video_path.is_relative_to(source_dir.resolve()):
            raise ValueError(f"Video path escapes intake bundle: {recording_id}")

        actual_sha256 = sha256_file(video_path)
        actual_byte_length = video_path.stat().st_size
        expected_sha256 = {
            "handoff": entry["source_group"]["source_sha256"],
            "manifest_video": video_entry["sha256"],
            "manifest_source": manifest["source_sha256"],
            "source_record": source_record["sha256"],
        }
        mismatches = {
            name: expected
            for name, expected in expected_sha256.items()
            if expected != actual_sha256
        }
        if actual_byte_length != video_entry["byte_length"]:
            mismatches["manifest_byte_length"] = video_entry["byte_length"]
        if actual_byte_length != source_record["byte_length"]:
            mismatches["source_record_byte_length"] = source_record["byte_length"]

        result = {
            "recording_id": recording_id,
            "relative_path": video_path.relative_to(ROOT).as_posix(),
            "byte_length": actual_byte_length,
            "sha256": actual_sha256,
            "expected_sha256": expected_sha256,
            "status": "verified" if not mismatches else "failed",
            "mismatches": mismatches,
        }
        recordings.append(result)
        if mismatches:
            failures.append(recording_id)

    report = {
        "schema_version": "0088-m1-source-verification/v1",
        "verified_on": "2026-10-16",
        "source_handoff": HANDOFF.relative_to(ROOT).as_posix(),
        "source_handoff_sha256": hashlib.sha256(HANDOFF.read_bytes()).hexdigest(),
        "recording_count": len(recordings),
        "verified_recording_count": len(recordings) - len(failures),
        "failed_recordings": failures,
        "recordings": recordings,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit(f"Source verification failed for: {', '.join(failures)}")
    print(f"Verified exact source bytes for all {len(recordings)} 0086 M5 recordings.")


if __name__ == "__main__":
    main()
