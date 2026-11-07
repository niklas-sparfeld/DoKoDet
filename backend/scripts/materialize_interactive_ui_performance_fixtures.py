#!/usr/bin/env python3
"""Build a seeded, disposable storage corpus for interactive UI performance work."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import tempfile
from pathlib import Path

SOURCE_MANIFEST = Path(__file__).parents[1] / "fixtures/interactive-ui-performance/v1/manifest.json"
SOURCE_DATA = json.loads(SOURCE_MANIFEST.read_text())
SEED = SOURCE_DATA["seed"]
PROFILES = SOURCE_DATA["profiles"]
HARD_ASSETS = tuple((asset["path"], asset["sha256"]) for asset in SOURCE_DATA["assets"])


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(root: Path, relative: str, value: object | bytes) -> dict[str, object]:
    content = value if isinstance(value, bytes) else _json_bytes(value)
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "path": relative,
        "sha256": hashlib.sha256(content).hexdigest(),
        "byte_length": len(content),
    }


def materialize(output: Path, profile: str) -> dict[str, object]:
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile {profile!r}; choose one of {', '.join(PROFILES)}")
    repository_root = Path(__file__).resolve().parents[2]
    if output.resolve().is_relative_to(repository_root):
        raise ValueError(f"Disposable output must be outside the repository: {output}")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Disposable output must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    sizes = PROFILES[profile]
    rng = random.Random(SEED)
    files: list[dict[str, object]] = []
    recording_ids = [f"perf-{i:05d}" for i in range(sizes["recordings"])]
    files.append(
        _write(
            output,
            "catalog/recordings.json",
            {
                "schema_version": "performance-recordings/v1",
                "recordings": [
                    {
                        "recording_id": rid,
                        "duration_us": 600_000_000 + i,
                        "video": f"media/{rid}.bin",
                    }
                    for i, rid in enumerate(recording_ids)
                ],
            },
        )
    )
    node_ids = [f"node-{i:06d}" for i in range(sizes["nodes"])]
    revisions_per_node = max(1, sizes["revisions"] // len(node_ids))
    for index, node_id in enumerate(node_ids):
        recording_id = recording_ids[index % len(recording_ids)]
        predecessor = node_ids[index - 1] if index else None
        manifest = {
            "schema_version": "pipeline-node/v1",
            "node_id": node_id,
            "name": f"Performance node {index}",
            "content_type": "events",
            "recording_id": recording_id,
            "source_node_id": predecessor,
            "source_revision_id": f"{predecessor}-r{revisions_per_node:04d}"
            if predecessor
            else None,
        }
        files.append(_write(output, f"pipeline/nodes/{node_id}/manifest.json", manifest))
        files.append(
            _write(
                output,
                f"pipeline/nodes/{node_id}/head.json",
                {
                    "schema_version": "pipeline-node-head/v1",
                    "revision_id": f"{node_id}-r{revisions_per_node:04d}",
                },
            )
        )
        for revision_index in range(revisions_per_node):
            revision_id = f"{node_id}-r{revision_index + 1:04d}"
            item_count = (
                sizes["items"] if index == 0 and revision_index == revisions_per_node - 1 else 2
            )
            items = [
                {
                    "event_id": f"{revision_id}-e{item:04d}",
                    "timestamp_us": item * 250_000,
                    "kind": "card_play",
                }
                for item in range(item_count)
            ]
            payload = {"schema_version": "events/v1", "recording_id": recording_id, "events": items}
            files.append(_write(output, f"pipeline/revisions/{revision_id}.json", payload))
    for index in range(sizes["jobs"]):
        job_id = f"job-{index:07d}"
        files.append(
            _write(
                output,
                f"operations/jobs/{job_id}.json",
                {
                    "schema_version": "backend-job/v1",
                    "job_id": job_id,
                    "recording_id": recording_ids[index % len(recording_ids)],
                    "status": ("completed", "queued", "failed")[index % 3],
                    "created_order": index,
                    "payload_token": rng.getrandbits(64),
                },
            )
        )
    media_size = 64 * 1024
    for index, recording_id in enumerate(recording_ids):
        media = bytes([index % 251]) * media_size
        files.append(_write(output, f"media/{recording_id}.bin", media))
    manifest = {
        "schema_version": "interactive-performance-fixtures/v1",
        "profile": profile,
        "seed": SEED,
        "sizes": sizes,
        "files": sorted(files, key=lambda item: str(item["path"])),
        "source_snapshots": [],
    }
    _write(output, "fixture-manifest.json", manifest)
    validate(output)
    return manifest


def import_hard_snapshot(repository: Path, cache: Path) -> list[dict[str, object]]:
    """Copy the frozen local example into digest-addressed cache paths after hash checks."""
    imported = []
    for relative, expected_hash in HARD_ASSETS:
        source = repository / relative
        if not source.is_file():
            raise ValueError(f"Missing hard snapshot source asset: {source}")
        actual_hash = _file_sha256(source)
        if actual_hash != expected_hash:
            raise ValueError(f"Hard snapshot hash mismatch for {relative}: {actual_hash}")
        target = cache / "sha256" / expected_hash
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and _file_sha256(target) != expected_hash:
            raise ValueError(f"Corrupt content-addressed hard asset: {target}")
        if not target.exists():
            try:
                os.link(source, target)
            except OSError:
                shutil.copyfile(source, target)
        imported.append(
            {"source": relative, "sha256": expected_hash, "byte_length": source.stat().st_size}
        )
    return imported


def validate_hard_snapshot(cache: Path) -> list[dict[str, object]]:
    verified = []
    for relative, expected_hash in HARD_ASSETS:
        path = cache / "sha256" / expected_hash
        if not path.is_file():
            raise ValueError(
                f"Missing required hard snapshot asset {expected_hash} for {relative}; "
                "run the documented --import-hard command or restore the content-addressed asset."
            )
        digest = _file_sha256(path)
        if digest != expected_hash:
            raise ValueError(f"Hard snapshot hash mismatch for {relative}: {digest}")
        verified.append({"source": relative, "sha256": digest, "byte_length": path.stat().st_size})
    assets = {relative: cache / "sha256" / digest for relative, digest in HARD_ASSETS}
    intake_manifest = json.loads(assets[HARD_ASSETS[0][0]].read_text())
    source_record = json.loads(assets[HARD_ASSETS[1][0]].read_text())
    node_manifest = json.loads(assets[HARD_ASSETS[3][0]].read_text())
    node_head = json.loads(assets[HARD_ASSETS[4][0]].read_text())
    revision = json.loads(assets[HARD_ASSETS[5][0]].read_text())
    video_relative, video_hash = HARD_ASSETS[2]
    video = assets[video_relative]
    if intake_manifest.get("schema_version") != "repository-bundle/v1":
        raise ValueError("Unsupported frozen recording manifest schema")
    if source_record.get("schema_version") != "source-record/v1":
        raise ValueError("Unsupported frozen recording source schema")
    if node_manifest.get("schema_version") != "pipeline-node/v1":
        raise ValueError("Unsupported frozen pipeline node schema")
    if node_head.get("revision_id") != revision.get("revision_id"):
        raise ValueError("Frozen node head does not reference the frozen exact revision")
    if revision.get("schema_version") != "pipeline-node-revision/v1":
        raise ValueError("Unsupported frozen pipeline revision schema")
    if revision.get("node_id") != node_manifest.get("node_id"):
        raise ValueError("Frozen revision belongs to a different pipeline node")
    hard_case = SOURCE_DATA["hard_example"]
    if intake_manifest.get("recording_id") != hard_case["recording_id"]:
        raise ValueError("Frozen repository bundle does not match the selected recording")
    if node_manifest.get("node_id") != hard_case["node_id"]:
        raise ValueError("Frozen pipeline node does not match the selected hard example")
    if revision.get("revision_id") != hard_case["revision_id"]:
        raise ValueError("Frozen revision does not match the selected exact revision")
    video_source = node_manifest.get("source", {})
    if video_source.get("recording_id") != intake_manifest.get("recording_id"):
        raise ValueError("Frozen node recording does not match the media dependency")
    if video_source.get("video_sha256") != video_hash or _file_sha256(video) != video_hash:
        raise ValueError("Frozen media identity does not match the pipeline node")
    if video_source.get("byte_length") != video.stat().st_size:
        raise ValueError("Frozen media byte length does not match the pipeline node")
    if (
        intake_manifest.get("files", {}).get("video", {}).get("sha256") != video_hash
        or source_record.get("sha256") != video_hash
        or source_record.get("recording_id") != intake_manifest.get("recording_id")
    ):
        raise ValueError(
            "Frozen media identity does not match the repository bundle and source record"
        )
    canonical_content = _json_bytes(revision.get("content"))[:-1]
    if hashlib.sha256(canonical_content).hexdigest() != revision.get("content_sha256"):
        raise ValueError("Frozen revision content digest is invalid")
    if len(revision.get("content", {}).get("frames", [])) != hard_case["evidence"]["frame_count"]:
        raise ValueError("Frozen revision frame count changed from the selected inventory evidence")
    return verified


def validate(root: Path) -> dict[str, object]:
    manifest_path = root / "fixture-manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"Missing fixture manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != "interactive-performance-fixtures/v1":
        raise ValueError("Unsupported interactive performance fixture manifest schema")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("Fixture manifest files must be a list")
    expected = {item["path"] for item in files}
    for entry in files:
        path = root / entry["path"]
        if not path.is_file():
            raise ValueError(f"Missing required fixture asset: {entry['path']}")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise ValueError(f"Fixture hash mismatch: {entry['path']}")
        if len(content) != entry["byte_length"]:
            raise ValueError(f"Fixture byte length mismatch: {entry['path']}")
    for relative in ("catalog/recordings.json",):
        if relative not in expected:
            raise ValueError(f"Fixture dependency closure is missing {relative}")
    catalog = json.loads((root / "catalog/recordings.json").read_text())
    recording_ids = {item["recording_id"] for item in catalog["recordings"]}
    node_manifests = [root / p for p in expected if p.endswith("/manifest.json") and "/nodes/" in p]
    node_ids = set()
    for path in node_manifests:
        node = json.loads(path.read_text())
        if node.get("schema_version") != "pipeline-node/v1":
            raise ValueError(f"Unsupported node schema in {path.relative_to(root)}")
        if node["recording_id"] not in recording_ids:
            raise ValueError(f"Unknown recording dependency in {path.relative_to(root)}")
        node_ids.add(node["node_id"])
    for path in node_manifests:
        node = json.loads(path.read_text())
        source_node = node.get("source_node_id")
        source_revision = node.get("source_revision_id")
        if bool(source_node) != bool(source_revision):
            raise ValueError(f"Incomplete lineage in {path.relative_to(root)}")
        if source_node and source_node not in node_ids:
            raise ValueError(f"Missing lineage node {source_node}")
        if source_revision and f"pipeline/revisions/{source_revision}.json" not in expected:
            raise ValueError(f"Missing lineage revision {source_revision}")
    for recording in catalog["recordings"]:
        media = recording["video"]
        if media not in expected:
            raise ValueError(f"Missing media dependency {media}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="representative")
    parser.add_argument(
        "--output", type=Path, help="Empty disposable directory; defaults to a new temp directory"
    )
    parser.add_argument("--validate", type=Path, help="Validate an existing materialized corpus")
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument(
        "--hard-cache",
        type=Path,
        default=Path.home() / ".cache/doko-detector/interactive-performance",
    )
    parser.add_argument(
        "--import-hard",
        action="store_true",
        help="Copy frozen local hard assets into the content-addressed cache",
    )
    parser.add_argument(
        "--require-hard",
        action="store_true",
        help="Require every frozen hard asset in the content-addressed cache",
    )
    args = parser.parse_args()
    if args.import_hard:
        try:
            entries = import_hard_snapshot(args.repository, args.hard_cache)
        except (OSError, ValueError) as error:
            print(f"Hard snapshot import failed: {error}")
            return 2
        print(f"Imported {len(entries)} verified hard assets into {args.hard_cache}")
    if args.require_hard:
        try:
            entries = validate_hard_snapshot(args.hard_cache)
        except (OSError, ValueError) as error:
            print(f"Hard snapshot validation failed: {error}")
            return 2
        print(f"Verified {len(entries)} hard snapshot assets in {args.hard_cache}")
    if args.validate:
        validate(args.validate)
        print(f"Validated fixture corpus: {args.validate}")
    if not (args.validate or args.import_hard or args.require_hard):
        output = args.output or Path(tempfile.mkdtemp(prefix="doko-perf-fixtures-"))
        try:
            manifest = materialize(output, args.profile)
        except (OSError, ValueError) as error:
            print(f"Fixture materialization failed: {error}")
            return 2
        print(f"Materialized {manifest['profile']} corpus in disposable storage: {output}")
        print(f"Seed {SEED}; {len(manifest['files'])} hashed assets")
        print(f"Manifest: {output / 'fixture-manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
