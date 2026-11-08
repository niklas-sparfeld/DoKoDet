#!/usr/bin/env python3
"""Convert one frozen PPM crop-cache snapshot into the v2 gzip representation."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import statistics
import time
from pathlib import Path
from typing import Any

from doko_operations.derived_view import (
    DERIVED_VIEW_CACHE_CODEC,
    DERIVED_VIEW_CACHE_COMPRESSED_SCHEMA,
    VISIBLE_REGION_CROP_SCHEMA,
)

FROZEN_ENTRY_COUNT = 8_571
FROZEN_SOURCE_DIGEST = "6721e55f6edc3c3d1f9f0602e0c77ffc1fd553e6acee6d15a39397cd2ae70381"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _selected(root: Path) -> list[tuple[str, Path, dict[str, Any]]]:
    result = []
    for manifest_path in root.rglob("manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        identity = manifest.get("identity") if isinstance(manifest, dict) else None
        if (
            isinstance(manifest, dict)
            and manifest.get("view_kind") == VISIBLE_REGION_CROP_SCHEMA
            and isinstance(identity, dict)
            and identity.get("output_encoding") == "ppm"
            and manifest.get("schema_version") == "derived-view-cache/v1"
        ):
            result.append((manifest_path.parent.name, manifest_path, manifest))
    return sorted(result, key=lambda row: row[0])


def source_snapshot(root: Path) -> dict[str, Any]:
    rows = _selected(root)
    leaves: list[str] = []
    logical_bytes = 0
    for key, manifest_path, manifest in rows:
        content = (manifest_path.parent / "content.bin").read_bytes()
        if (
            manifest.get("cache_key") != key
            or len(content) != manifest.get("byte_length")
            or _sha256(content) != manifest.get("content_sha256")
            or manifest.get("identity", {}).get("image_sha256") != manifest.get("content_sha256")
        ):
            raise ValueError(f"source entry failed identity check: {key}")
        identity = json.dumps(
            manifest["identity"], sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        leaves.append(_sha256(f"{key}\0{identity}".encode()))
        logical_bytes += len(content)
    return {
        "entries": len(rows),
        "source_digest": _sha256("".join(sorted(leaves)).encode()),
        "logical_content_bytes": logical_bytes,
        "keys": [row[0] for row in rows],
    }


def convert(
    source: Path,
    destination: Path,
    *,
    stop_after: int | None = None,
    expected_entries: int = FROZEN_ENTRY_COUNT,
    expected_digest: str = FROZEN_SOURCE_DIGEST,
) -> dict[str, Any]:
    source = source.resolve()
    destination = destination.resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("source and destination must be separate, non-nested roots")
    if destination.exists():
        raise ValueError(f"destination already exists: {destination}")
    frozen = source_snapshot(source)
    rows = _selected(source)
    if not rows:
        raise ValueError(f"no v1 PPM crop entries under {source}")
    if frozen["entries"] != expected_entries or frozen["source_digest"] != expected_digest:
        raise ValueError("source does not match the frozen M11 crop-cache snapshot")
    started = time.perf_counter_ns()
    destination.mkdir(parents=True)
    stored_bytes = 0
    write_started = time.perf_counter_ns()
    try:
        for index, (key, manifest_path, manifest) in enumerate(rows, 1):
            content = (manifest_path.parent / "content.bin").read_bytes()
            stored = gzip.compress(content, compresslevel=1, mtime=0)
            replacement = dict(manifest)
            replacement.update(
                {
                    "schema_version": DERIVED_VIEW_CACHE_COMPRESSED_SCHEMA,
                    "storage_codec": DERIVED_VIEW_CACHE_CODEC,
                    "stored_content_sha256": _sha256(stored),
                    "stored_byte_length": len(stored),
                }
            )
            entry = destination / key
            entry.mkdir()
            (entry / "manifest.json").write_text(
                json.dumps(replacement, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            (entry / "content.bin.gz").write_bytes(stored)
            stored_bytes += len(stored)
            if stop_after is not None and index >= stop_after:
                raise InterruptedError(f"injected interruption after {index} entries")
        write_elapsed = time.perf_counter_ns() - write_started
        # Verify every converted item, including all exact identity and content fields.
        for key, _manifest_path, original in rows:
            entry = destination / key
            converted = json.loads((entry / "manifest.json").read_text(encoding="utf-8"))
            packed = (entry / "content.bin.gz").read_bytes()
            restored = gzip.decompress(packed)
            if (
                converted["storage_codec"] != DERIVED_VIEW_CACHE_CODEC
                or converted["stored_byte_length"] != len(packed)
                or converted["stored_content_sha256"] != _sha256(packed)
                or restored != (source / key / "content.bin").read_bytes()
                or converted["identity"] != original["identity"]
                or converted["content_sha256"] != original["content_sha256"]
                or converted["byte_length"] != original["byte_length"]
            ):
                raise ValueError(f"converted entry failed exact verification: {key}")
        sample = random.Random(11511).sample([row[0] for row in rows], min(128, len(rows)))
        read_times: list[list[int]] = [[], []]
        from doko_operations.derived_view import DerivedViewCache

        cache = DerivedViewCache(destination)
        for pass_times in read_times:
            for key in sample:
                read_started = time.perf_counter_ns()
                if cache.read(key) is None:
                    raise ValueError(f"converted entry failed application read: {key}")
                pass_times.append(time.perf_counter_ns() - read_started)

        def p95(times: list[int]) -> int:
            return sorted(times)[int(0.95 * (len(times) - 1))]

        elapsed = time.perf_counter_ns() - started
        return {
            "source_snapshot": {k: v for k, v in frozen.items() if k != "keys"},
            "converted_entries": len(rows),
            "stored_content_bytes": stored_bytes,
            "allocated_bytes": sum(
                path.stat().st_blocks * 512 for path in destination.rglob("*") if path.is_file()
            ),
            "files": sum(1 for path in destination.rglob("*") if path.is_file()),
            "convert_verify_elapsed_ns": elapsed,
            "store_encode_write_elapsed_ns": write_elapsed,
            "average_store_encode_write_ms_per_entry": (write_elapsed / len(rows) / 1_000_000),
            "random_sample_n": len(sample),
            "random_sample_key_set_sha256": _sha256("".join(sorted(sample)).encode()),
            "cold_random_read_median_ns": int(statistics.median(read_times[0])),
            "cold_random_read_p95_ns": p95(read_times[0]),
            "warm_random_read_median_ns": int(statistics.median(read_times[1])),
            "warm_random_read_p95_ns": p95(read_times[1]),
        }
    except BaseException:
        # Leave partial output in place to prove interruption handling; callers can
        # inspect it, then remove the disposable target and repeat from the frozen source.
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = convert(
            args.source.expanduser(), args.destination.expanduser(), stop_after=args.stop_after
        )
    except (OSError, ValueError, KeyError, TypeError, InterruptedError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"Converted {result['converted_entries']} entries to {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
