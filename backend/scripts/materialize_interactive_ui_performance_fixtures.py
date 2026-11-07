#!/usr/bin/env python3
"""Build a seeded, disposable storage corpus for interactive UI performance work."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

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


def _inventory_files(root: Path) -> list[dict[str, object]]:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == "fixture-manifest.json":
            continue
        files.append(
            {
                "path": relative,
                "sha256": _file_sha256(path),
                "byte_length": path.stat().st_size,
            }
        )
    return files


def _materialize_nodes(
    root: Path,
    sizes: dict[str, int],
    recording_ids: list[str],
    media: dict[str, dict[str, object]],
) -> None:
    from unittest.mock import patch

    import dokodetector_backend.pipeline_node_store as node_store_module
    from dokodetector_backend.pipeline_node_store import PipelineNodeStore

    store = PipelineNodeStore(root / "pipeline" / "nodes")
    node_ids = [
        str(uuid5(NAMESPACE_URL, f"doko-perf-{SEED}-node-{i}")) for i in range(sizes["nodes"])
    ]
    revisions_per_node = sizes["revisions"] // len(node_ids)
    timestamp = datetime(2026, 11, 7, tzinfo=UTC).isoformat()
    root_revision_ids: dict[str, str] = {}
    with patch.object(node_store_module, "_canonical_timestamp", return_value=timestamp):
        for index, node_id in enumerate(node_ids):
            recording_id = recording_ids[index % len(recording_ids)]
            source = {
                "schema_version": "recording-video/v1",
                "recording_id": recording_id,
                "relative_path": f"media/{recording_id}.bin",
                "video_sha256": media[recording_id]["sha256"],
                "byte_length": media[recording_id]["byte_length"],
                "duration_us": 600_000_000 + index,
            }
            root_revision_id = root_revision_ids.get(recording_id)
            metadata = (
                {
                    "copied_from": {
                        "node_id": node_ids[recording_ids.index(recording_id)],
                        "revision_id": root_revision_id,
                    }
                }
                if root_revision_id
                else {}
            )
            latest_revision_id = None
            for revision_index in range(revisions_per_node):
                item_count = (
                    sizes["items"] if index == 0 and revision_index == revisions_per_node - 1 else 2
                )
                content = {
                    "schema_version": "event-data/v1",
                    "events": [
                        {
                            "event_id": f"perf-{index:05d}-{revision_index:04d}-{item:04d}",
                            "event_type": "card_state_changed",
                            "start_us": item * 250_000,
                            "end_us": item * 250_000,
                        }
                        for item in range(item_count)
                    ],
                }
                revision_id = str(
                    uuid5(NAMESPACE_URL, f"doko-perf-{SEED}-{index}-{revision_index}")
                )
                if revision_index == 0:
                    revision = store.create(
                        node_id,
                        f"Performance node {index}",
                        "events",
                        source,
                        content,
                        metadata,
                        revision_id=revision_id,
                    )
                else:
                    assert latest_revision_id is not None
                    revision = store.save(
                        node_id,
                        latest_revision_id,
                        content,
                        metadata,
                        revision_id=revision_id,
                    )
                latest_revision_id = revision.revision_id
            if recording_id not in root_revision_ids:
                assert latest_revision_id is not None
                root_revision_ids[recording_id] = latest_revision_id


def _materialize_jobs(root: Path, sizes: dict[str, int], recording_ids: list[str]) -> None:
    from dokodetector_backend.job_store import Job, JobRequest, _digest

    timestamp = datetime(2026, 11, 7, tzinfo=UTC).isoformat()
    for index in range(sizes["jobs"]):
        recording_id = recording_ids[index % len(recording_ids)]
        request = JobRequest(
            type="fake",
            context={"recording_id": recording_id},
            request={"input": f"perf-input-{index:07d}"},
        )
        job_id = str(uuid5(NAMESPACE_URL, f"doko-perf-{SEED}-job-{index}"))
        idempotency_key = str(uuid5(NAMESPACE_URL, f"doko-perf-{SEED}-job-key-{index}"))
        state = ("succeeded", "queued", "failed")[index % 3]
        job = Job(
            id=job_id,
            type=request.type,
            label="Performance fixture job",
            context=request.context,
            request=request.request,
            idempotency_key=idempotency_key,
            request_hash=_digest(request),
            state=state,
            created_at=timestamp,
            updated_at=timestamp,
            started_at=timestamp if state != "queued" else None,
            finished_at=timestamp if state in {"succeeded", "failed"} else None,
            correlation_id=f"perf-correlation-{index:07d}",
        )
        _write(root, f"operations/jobs/{job_id}/job.json", job.model_dump(mode="json"))


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
    recording_ids = [f"perf-{i:05d}" for i in range(sizes["recordings"])]
    media_size = 64 * 1024
    media: dict[str, dict[str, object]] = {}
    for index, recording_id in enumerate(recording_ids):
        content = bytes([index % 251]) * media_size
        entry = _write(output, f"media/{recording_id}.bin", content)
        media[recording_id] = {"sha256": entry["sha256"], "byte_length": media_size}
    _materialize_nodes(output, sizes, recording_ids, media)
    _materialize_jobs(output, sizes, recording_ids)
    manifest = {
        "schema_version": "interactive-performance-fixtures/v1",
        "profile": profile,
        "seed": SEED,
        "sizes": sizes,
        "files": _inventory_files(output),
        "source_manifest_sha256": _file_sha256(SOURCE_MANIFEST),
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
    import tempfile

    from doko_operations.card_plane_calibration import CalibrationRevisionStore
    from doko_operations.card_plane_calibration_refinement import CalibrationDraftStore

    from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
    from dokodetector_backend.pipeline_node_store import PipelineNodeStore
    from dokodetector_backend.recording_bundle_store import RecordingBundleStore
    from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage

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
    with tempfile.TemporaryDirectory(prefix="verify-", dir=cache) as temporary:
        snapshot_root = Path(temporary)
        for relative, digest in HARD_ASSETS:
            source = cache / "sha256" / digest
            target = snapshot_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, target)

        bundle_store = RecordingBundleStore(
            RepositoryBundleStorage(snapshot_root / "data/intake/recordings")
        )
        for example in SOURCE_DATA["examples"]:
            recording_id = example["recording_id"]
            if bundle_store.get_metadata(recording_id) is None:
                raise ValueError(f"Frozen recording bundle is invalid: {recording_id}")

        node_store = PipelineNodeStore(snapshot_root / "data/operations/pipeline-nodes")
        for example in SOURCE_DATA["examples"]:
            node_id = example.get("node_id")
            if node_id is None:
                continue
            node = node_store.get(node_id)
            source_video = snapshot_root / node.source["relative_path"]
            if (
                not source_video.is_file()
                or _file_sha256(source_video) != node.source["video_sha256"]
            ):
                raise ValueError(f"Frozen node media dependency is invalid: {node_id}")
            if node.source["byte_length"] != source_video.stat().st_size:
                raise ValueError(f"Frozen node media size is invalid: {node_id}")
            revision_root = node_store.root / node_id / "revisions"
            revision_ids = {path.name for path in revision_root.iterdir() if path.is_dir()}
            if not revision_ids:
                raise ValueError(f"Frozen node has no revisions: {node_id}")
            for revision_id in revision_ids:
                node_store.read_revision(node_id, revision_id)
            exact_revision = example.get("revision_id")
            if exact_revision and exact_revision not in revision_ids:
                raise ValueError(f"Frozen exact revision is absent: {node_id}/{exact_revision}")

        fanout = next(
            example
            for example in SOURCE_DATA["examples"]
            if example["kind"] == "copy-lineage-fanout"
        )
        reviews = PipelineNodeReviews(node_store)
        for node_id in fanout["node_ids"]:
            node = node_store.get(node_id)
            reviews.applicable_for_revision(node_id, node.head_revision_id)

        draft_case = next(
            example
            for example in SOURCE_DATA["examples"]
            if example["kind"] == "calibration-review-draft"
        )
        CalibrationDraftStore(snapshot_root / "data/operations/calibration-refinement-drafts").load(
            draft_case["recording_id"], draft_case["draft_id"]
        )
        run = CalibrationRevisionStore(snapshot_root / "data/operations").load(
            draft_case["recording_id"], draft_case["calibration_revision_id"]
        )
        if run.calibration is None:
            raise ValueError("Frozen base calibration revision has no calibration data")
    return verified


def validate(root: Path) -> dict[str, object]:
    from dokodetector_backend.job_store import Job, JobManager
    from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
    from dokodetector_backend.pipeline_node_store import PipelineNodeStore

    manifest_path = root / "fixture-manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"Missing fixture manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != "interactive-performance-fixtures/v1":
        raise ValueError("Unsupported interactive performance fixture manifest schema")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("Fixture manifest files must be a list")
    for entry in files:
        path = root / entry["path"]
        if not path.is_file():
            raise ValueError(f"Missing required fixture asset: {entry['path']}")
        if _file_sha256(path) != entry["sha256"]:
            raise ValueError(f"Fixture hash mismatch: {entry['path']}")
        if path.stat().st_size != entry["byte_length"]:
            raise ValueError(f"Fixture byte length mismatch: {entry['path']}")
    media_entries = {
        Path(str(entry["path"])).stem: entry
        for entry in files
        if str(entry["path"]).startswith("media/")
    }
    if len(media_entries) != manifest["sizes"]["recordings"]:
        raise ValueError("Fixture recording count does not match its materialized media assets")
    node_store = PipelineNodeStore(root / "pipeline" / "nodes")
    nodes = node_store.list_nodes()
    if len(nodes) != manifest["sizes"]["nodes"]:
        raise ValueError("Production node store returned an unexpected node count")
    revisions_seen = 0
    copied_nodes = []
    lineage_targets = []
    for node in nodes:
        source_media = root / node.source["relative_path"]
        media_entry = media_entries.get(node.source["recording_id"])
        if media_entry is None or not source_media.is_file():
            raise ValueError(f"Missing source media for node {node.node_id}")
        if node.source["video_sha256"] != media_entry["sha256"]:
            raise ValueError(f"Node media identity mismatch for {node.node_id}")
        if node.source["byte_length"] != media_entry["byte_length"]:
            raise ValueError(f"Node media size mismatch for {node.node_id}")
        revision_root = root / "pipeline" / "nodes" / node.node_id / "revisions"
        node_revision_paths = sorted(revision_root.iterdir())
        if len(node_revision_paths) > 1:
            lineage_targets.append((len(node_revision_paths), node.node_id, node.head_revision_id))
        for revision_path in node_revision_paths:
            revision = node_store.read_revision(node.node_id, revision_path.name)
            revisions_seen += 1
            if revision.parent_revision_id:
                node_store.read_revision(node.node_id, revision.parent_revision_id)
            copied_from = revision.metadata.get("copied_from")
            if copied_from:
                source_revision = node_store.read_revision(
                    copied_from["node_id"], copied_from["revision_id"]
                )
                copied_nodes.append((node.node_id, revision.revision_id))
                if not source_revision.content_sha256:
                    raise ValueError(
                        f"Copied source revision has no content digest: {node.node_id}"
                    )
    if revisions_seen != manifest["sizes"]["revisions"]:
        raise ValueError("Production node store returned an unexpected revision count")
    lineage_reader = PipelineNodeReviews(node_store)
    if copied_nodes:
        lineage_reader.applicable_for_revision(*copied_nodes[0])
    if lineage_targets:
        _, node_id, revision_id = max(lineage_targets)
        lineage_reader.applicable_for_revision(node_id, revision_id)
    job_paths = sorted((root / "operations" / "jobs").glob("*/job.json"))
    if len(job_paths) != manifest["sizes"]["jobs"]:
        raise ValueError("Fixture job count does not match its manifest")
    for job_path in job_paths:
        job = Job.model_validate_json(job_path.read_bytes())
        if job_path.parent.name != job.id:
            raise ValueError(f"Job ID does not match its storage path: {job_path}")
    if job_paths:
        with JobManager(root / "operations", participant=object()) as manager:
            # A generated profile has no acceptance intents. Ignore recovery diagnostics for
            # those deliberately standalone records, then exercise the production read path.
            manager.diagnostics.clear()
            for job_path in (job_paths[0], job_paths[-1]):
                if manager.get(job_path.parent.name).id != job_path.parent.name:
                    raise ValueError(f"Production job reader returned the wrong record: {job_path}")
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
