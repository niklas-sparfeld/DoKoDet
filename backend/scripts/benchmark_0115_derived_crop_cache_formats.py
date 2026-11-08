#!/usr/bin/env python3
"""Compare lossless storage choices for the M0-ranked PPM crop-cache family."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(".runtime/pipeline/derived-views")
LEVELS = {"gzip-1": 1, "gzip-6": 6}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _allocated_bytes(path: Path) -> int:
    return sum(item.stat().st_blocks * 512 for item in path.rglob("*") if item.is_file())


def _files(path: Path) -> list[Path]:
    return [item for item in path.rglob("*") if item.is_file()]


def _entries(root: Path) -> list[tuple[str, Path, Path, bytes, dict[str, Any]]]:
    found: list[tuple[str, Path, Path, bytes, dict[str, Any]]] = []
    for manifest_path in root.rglob("manifest.json"):
        try:
            manifest_bytes = manifest_path.read_bytes()
            manifest = json.loads(manifest_bytes)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        identity = manifest.get("identity")
        if (
            manifest.get("view_kind") == "visible-region-crop/v1"
            and isinstance(identity, dict)
            and identity.get("output_encoding") == "ppm"
        ):
            content_path = manifest_path.parent / "content.bin"
            if content_path.is_file():
                found.append(
                    (
                        manifest_path.parent.name,
                        manifest_path,
                        content_path,
                        manifest_bytes,
                        manifest,
                    )
                )
    found.sort(key=lambda row: row[0])
    return found


def _read_samples(
    root: Path,
    sample: list[tuple[str, Path, Path, bytes, dict[str, Any]]],
    codec: str,
) -> dict[str, int]:
    order = sample[:]
    random.Random(11511).shuffle(order)
    times: list[list[int]] = [[], []]
    parse_ns = 0
    peak = 0
    tracemalloc.start()
    for target in times:
        for key, _manifest_path, _content_path, _manifest_bytes, expected in order:
            entry = root / key
            tracemalloc.reset_peak()
            start = time.perf_counter_ns()
            raw_manifest = (entry / "manifest.json").read_bytes()
            started_parse = time.perf_counter_ns()
            manifest = json.loads(raw_manifest)
            parse_ns += time.perf_counter_ns() - started_parse
            if codec == "baseline":
                content = (entry / "content.bin").read_bytes()
            else:
                stored = (entry / "content.bin.gz").read_bytes()
                if (
                    len(stored) != manifest["stored_byte_length"]
                    or _sha256(stored) != manifest["stored_content_sha256"]
                ):
                    raise ValueError("stored compressed bytes do not match the manifest")
                content = gzip.decompress(stored)
            if (
                len(content) != manifest["byte_length"]
                or _sha256(content) != manifest["content_sha256"]
                or manifest["identity"] != expected["identity"]
            ):
                raise ValueError("restored cache identity or content differs")
            target.append(time.perf_counter_ns() - start)
            _, current_peak = tracemalloc.get_traced_memory()
            peak = max(peak, current_peak)
    tracemalloc.stop()

    def percentile95(values: list[int]) -> int:
        return sorted(values)[int(0.95 * (len(values) - 1))]

    return {
        "random_access_n": len(order),
        "cold_app_read_median_ns": int(statistics.median(times[0])),
        "cold_app_read_p95_ns": percentile95(times[0]),
        "warm_app_read_median_ns": int(statistics.median(times[1])),
        "warm_app_read_p95_ns": percentile95(times[1]),
        "manifest_parse_total_ns": parse_ns,
        "peak_tracemalloc_bytes": peak,
    }


def run(root: Path) -> dict[str, Any]:
    rows = _entries(root)
    if not rows:
        raise ValueError(f"no visible-region-crop/v1 PPM entries under {root}")
    total_content = total_manifest = current_allocated = 0
    identity_digests: list[str] = []
    for key, _manifest_path, content_path, manifest_bytes, manifest in rows:
        identity = manifest["identity"]
        content = content_path.read_bytes()
        if (
            len(content) != manifest["byte_length"]
            or _sha256(content) != manifest["content_sha256"]
            or identity.get("image_sha256") != manifest["content_sha256"]
        ):
            raise ValueError("source cache content does not match its manifest")
        total_content += len(content)
        total_manifest += len(manifest_bytes)
        current_allocated += _allocated_bytes(content_path.parent)
        identity_digests.append(
            _sha256(
                key.encode()
                + b"\0"
                + json.dumps(
                    identity, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
            )
        )
    identity_set_digest = _sha256("".join(sorted(identity_digests)).encode())

    rng = random.Random(11511)
    sample = rng.sample(rows, min(128, len(rows)))
    sample_key_digest = _sha256("".join(sorted(row[0] for row in sample)).encode())
    results: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="0115-m11-crop-formats-") as directory:
        temp_root = Path(directory)
        for codec, level in [("baseline", None), *LEVELS.items()]:
            destination = temp_root / codec
            destination.mkdir()
            store_ns = encode_ns = 0
            tracemalloc.start()
            peak = 0
            for key, _manifest_path, content_path, manifest_bytes, manifest in rows:
                tracemalloc.reset_peak()
                started = time.perf_counter_ns()
                original = content_path.read_bytes()
                if level is None:
                    stored = original
                    output_manifest = manifest_bytes
                    filename = "content.bin"
                else:
                    encode_started = time.perf_counter_ns()
                    stored = gzip.compress(original, compresslevel=level, mtime=0)
                    encode_ns += time.perf_counter_ns() - encode_started
                    replacement = dict(manifest)
                    replacement["schema_version"] = "derived-view-cache/v2"
                    replacement["storage_codec"] = f"gzip/level-{level}/v1"
                    replacement["stored_content_sha256"] = _sha256(stored)
                    replacement["stored_byte_length"] = len(stored)
                    output_manifest = (
                        json.dumps(replacement, sort_keys=True, separators=(",", ":")) + "\n"
                    ).encode()
                    filename = "content.bin.gz"
                entry = destination / key
                entry.mkdir()
                (entry / "manifest.json").write_bytes(output_manifest)
                (entry / filename).write_bytes(stored)
                store_ns += time.perf_counter_ns() - started
                _, current_peak = tracemalloc.get_traced_memory()
                peak = max(peak, current_peak)
            tracemalloc.stop()
            files = _files(destination)
            result = {
                "content_bytes": sum(
                    (item / ("content.bin" if level is None else "content.bin.gz")).stat().st_size
                    for item in destination.iterdir()
                ),
                "manifest_bytes": sum(
                    (item / "manifest.json").stat().st_size for item in destination.iterdir()
                ),
                "allocated_bytes": _allocated_bytes(destination),
                "file_count": len(files),
                "store_read_encode_manifest_write_total_ns": store_ns,
                "encode_ns": encode_ns,
                "peak_tracemalloc_bytes": peak,
            }
            if level is not None:
                verify_started = time.perf_counter_ns()
                for key, _mp, content_path, _mb, manifest in rows:
                    stored = (destination / key / "content.bin.gz").read_bytes()
                    candidate = json.loads((destination / key / "manifest.json").read_bytes())
                    restored = gzip.decompress(stored)
                    if (
                        len(stored) != candidate["stored_byte_length"]
                        or _sha256(stored) != candidate["stored_content_sha256"]
                        or restored != content_path.read_bytes()
                        or len(restored) != manifest["byte_length"]
                        or _sha256(restored) != manifest["content_sha256"]
                        or candidate["identity"] != manifest["identity"]
                    ):
                        raise ValueError("candidate failed exact content or identity verification")
                result["all_entry_exact_roundtrip_n"] = len(rows)
                result["exact_roundtrip_verification_ns"] = time.perf_counter_ns() - verify_started
            result.update(_read_samples(destination, sample, codec))
            results[codec] = result

    return {
        "schema_version": "0115-m11-format-benchmark/v1",
        "family": "derived-view cache visible-region-crop/v1, canonical PPM content",
        "entries": len(rows),
        "content_bytes": total_content,
        "manifest_bytes": total_manifest,
        "current_allocated_bytes": current_allocated,
        "current_files": 2 * len(rows),
        "identity_frame_geometry_exclusion_digest": identity_set_digest,
        "random_sample_n": len(sample),
        "random_sample_key_set_sha256": sample_key_digest,
        "cold_semantics": "first application lookup; OS file cache not flushed",
        "alternatives": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.root.expanduser())
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(f"Wrote format benchmark for {result['entries']} entries to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
