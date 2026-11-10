"""Bounded snapshot, rehearsal, and activation for recording event resources."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from doko_operations.pipeline_data import canonical_json_bytes

from dokodetector_backend.event_conversion_rehearsal import rehearse
from dokodetector_backend.recording_folder_store import RecordingFolderStore


class RolloutError(ValueError):
    """The frozen corpus cannot be rehearsed or activated without guessing."""


def build_snapshot(
    *, bundle_root: Path, recordings_root: Path, operations_root: Path
) -> dict[str, Any]:
    """Describe exact bundle, event, review, selector, and output-parent inputs."""
    nodes_root = operations_root / "pipeline-nodes"
    legacy_selection_root = operations_root / "pipeline" / "selections"
    node_selection_root = nodes_root / ".pipeline-node-selections"
    bundle_paths = sorted(bundle_root.glob("*/manifest.json"))
    if not bundle_paths:
        raise RolloutError("recording bundle corpus is empty")

    bundles: dict[str, dict[str, Any]] = {}
    for path in bundle_paths:
        recording_id = path.parent.name
        manifest = _read_json(path)
        source_path = path.parent / "source-record.json"
        enrollment_path = path.parent / "initial-task-enrollment.json"
        source = _read_json(source_path)
        bundles[recording_id] = {
            "manifest": _file_fact(path),
            "source_record": _file_fact(source_path),
            "enrollment": _file_fact(enrollment_path),
            "source_media": {
                "relative_path": manifest["files"]["video"]["relative_path"],
                "sha256": source["sha256"],
                "byte_length": source["byte_length"],
            },
            "proposal_files": [
                _file_fact(path.parent / item["relative_path"])
                for item in manifest["files"].get("proposal_generator_runs", [])
            ],
        }

    event_nodes: dict[str, list[dict[str, Any]]] = {key: [] for key in bundles}
    visible_nodes: dict[str, list[dict[str, Any]]] = {key: [] for key in bundles}
    event_node_ids: set[str] = set()
    for manifest_path in nodes_root.glob("*/manifest.json"):
        manifest = _read_json(manifest_path)
        recording_id = manifest.get("source", {}).get("recording_id")
        if recording_id not in bundles:
            continue
        content_type = manifest.get("content_type")
        if content_type not in {"events", "visible_cards"}:
            continue
        node_id = manifest["node_id"]
        if content_type == "events":
            event_node_ids.add(node_id)
        rows = event_nodes if content_type == "events" else visible_nodes
        rows[recording_id].append(_snapshot_node(manifest_path, manifest, content_type))

    reviews_by_node: dict[str, list[dict[str, Any]]] = {}
    review_root = nodes_root / ".review-records"
    for path in review_root.glob("*.json"):
        review = _read_json(path)
        if review.get("node_id") in event_node_ids:
            reviews_by_node.setdefault(review["node_id"], []).append(_file_fact(path))

    recordings = []
    for recording_id, bundle in bundles.items():
        old_selector = legacy_selection_root / recording_id / "events.json"
        node_selector = node_selection_root / recording_id / "events.json"
        events = sorted(event_nodes[recording_id], key=lambda row: row["node_id"])
        if not events:
            exception = "no retained event nodes"
        elif not old_selector.is_file():
            exception = "legacy event selector is missing"
        elif not node_selector.is_file():
            exception = "recording event selector is missing"
        else:
            exception = None
        recordings.append(
            {
                "recording_id": recording_id,
                "bundle": bundle,
                "event_nodes": events,
                "selectors": {
                    "legacy": _file_fact(old_selector) if old_selector.is_file() else None,
                    "recording": _file_fact(node_selector) if node_selector.is_file() else None,
                },
                "review_files": sorted(
                    (fact for node in events for fact in reviews_by_node.get(node["node_id"], [])),
                    key=lambda row: row["path"],
                ),
                "exception": exception,
            }
        )

    existing_roots = []
    recording_store = RecordingFolderStore(recordings_root)
    for root in recording_store.list():
        path = recording_store.recording_path(root.recording_id)
        existing_roots.append(
            {
                "recording_id": root.recording_id,
                "head": root.head,
                "recording_json": _file_fact(path / "recording.json"),
                "tree_sha256": _tree_sha256(path),
            }
        )

    snapshot = {
        "schema_version": "0124-event-corpus-snapshot/v1",
        "bundle_root": str(bundle_root.resolve()),
        "operations_root": str(operations_root.resolve()),
        "recordings_root": str(recordings_root.resolve()),
        "existing_recording_roots": existing_roots,
        "recordings": recordings,
        "visible_card_outputs": sorted(
            (
                output
                for rows in visible_nodes.values()
                for node in rows
                for output in node["revisions"]
            ),
            key=lambda row: (row["recording_id"], row["node_id"], row["revision_id"]),
        ),
    }
    snapshot["snapshot_sha256"] = hashlib.sha256(canonical_json_bytes(snapshot)).hexdigest()
    return snapshot


def rehearse_snapshot(
    *, snapshot: dict[str, Any], disposable_root: Path, existing_recordings_root: Path
) -> dict[str, Any]:
    """Copy and convert the frozen corpus only under a disposable root."""
    _verify_snapshot(snapshot)
    if disposable_root.exists() and any(disposable_root.iterdir()):
        raise RolloutError("disposable rollout root must be empty")
    recordings_root = disposable_root / "recordings"
    operations_root = disposable_root / "operations"
    recordings_root.mkdir(parents=True)
    operations_root.mkdir(parents=True)
    shutil.copytree(
        snapshot["operations_root"] + "/pipeline-nodes",
        operations_root / "pipeline-nodes",
    )
    shutil.copytree(
        snapshot["operations_root"] + "/pipeline/selections",
        operations_root / "pipeline" / "selections",
    )
    _copy_existing_roots(existing_recordings_root, recordings_root)
    _import_missing_bundles(Path(snapshot["bundle_root"]), recordings_root, snapshot)
    receipt = _convert_usable(snapshot, recordings_root, operations_root)
    receipt["snapshot_sha256"] = snapshot["snapshot_sha256"]
    receipt["recording_roots"] = len(RecordingFolderStore(recordings_root).list())
    return receipt


def activate_snapshot(
    *,
    snapshot: dict[str, Any],
    rehearsal_receipt: dict[str, Any],
    recovery_path: Path,
) -> dict[str, Any]:
    """Activate only a rehearsed snapshot and record the previous user state first."""
    _verify_snapshot(snapshot)
    if rehearsal_receipt.get("snapshot_sha256") != snapshot["snapshot_sha256"]:
        raise RolloutError("rehearsal receipt does not match the frozen corpus")
    if rehearsal_receipt.get("conversion", {}).get("review_count", 0) < 0:
        raise RolloutError("rehearsal receipt is invalid")

    bundle_root = Path(snapshot["bundle_root"])
    operations_root = Path(snapshot["operations_root"])
    recordings_root = Path(snapshot["recordings_root"])
    preexisting = RecordingFolderStore(recordings_root)
    roots_before = []
    for root in preexisting.list():
        tree = preexisting.recording_path(root.recording_id)
        roots_before.append(
            {
                "recording_id": root.recording_id,
                "recording_json_sha256": _sha256_file(tree / "recording.json"),
                "recording_json": (tree / "recording.json").read_text(),
                "head": root.head,
                "tree_sha256": _tree_sha256(tree),
            }
        )
    preexisting_event_versions = _event_version_keys(recordings_root)
    recovery = {
        "schema_version": "0124-event-corpus-recovery/v1",
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "recordings_root": str(recordings_root.resolve()),
        "preexisting_recording_roots": roots_before,
        "preexisting_event_versions": sorted(preexisting_event_versions),
        "new_recording_ids": sorted(
            {row["recording_id"] for row in snapshot["recordings"]}
            - {row["recording_id"] for row in roots_before}
        ),
        "rollback": (
            "Remove only recording roots absent from preexisting_recording_roots. For preexisting "
            "roots, remove only event-set versions absent from preexisting_event_versions and "
            "restore the saved recording.json bytes after verifying their original digest."
        ),
    }
    _atomic_json(recovery_path, recovery)

    _import_missing_bundles(bundle_root, recordings_root, snapshot)
    conversion = _convert_usable(snapshot, recordings_root, operations_root)
    roots_after = RecordingFolderStore(recordings_root)
    head_changes = []
    before_by_id = {row["recording_id"]: row for row in roots_before}
    for recording in roots_after.list():
        before = before_by_id.get(recording.recording_id)
        if before is not None and recording.head != before["head"]:
            head_changes.append(recording.recording_id)
    if head_changes:
        raise RolloutError(f"activation changed a preexisting recording HEAD: {head_changes}")
    after_versions = _event_version_keys(recordings_root)
    activated = {
        "schema_version": "0124-event-corpus-activation/v1",
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "recording_roots": len(roots_after.list()),
        "event_versions_added": len(after_versions - preexisting_event_versions),
        "event_versions": len(after_versions),
        "head_changes": head_changes,
        "conversion": conversion,
        "recovery_path": str(recovery_path.resolve()),
    }
    return activated


def _convert_usable(
    snapshot: dict[str, Any], recordings_root: Path, operations_root: Path
) -> dict[str, Any]:
    usable = tuple(
        row["recording_id"] for row in snapshot["recordings"] if row["exception"] is None
    )
    exceptions = [
        {"recording_id": row["recording_id"], "reason": row["exception"]}
        for row in snapshot["recordings"]
        if row["exception"] is not None
    ]
    conversion = rehearse(
        recordings_root=recordings_root,
        pipeline_nodes_root=operations_root / "pipeline-nodes",
        legacy_pipeline_root=operations_root / "pipeline",
        recording_ids=usable,
    )
    parent_report = _output_parent_report(snapshot, conversion)
    return {
        "converted_recording_count": len(usable),
        "exception_recordings": exceptions,
        "conversion": conversion,
        "output_parents": parent_report,
    }


def _output_parent_report(snapshot: dict[str, Any], conversion: dict[str, Any]) -> dict[str, Any]:
    versions = {row["recording_id"]: row["converted_versions"] for row in conversion["recordings"]}
    legacy_rows = {
        row["recording_id"]: [
            revision for node in row["event_nodes"] for revision in node["revisions"]
        ]
        for row in snapshot["recordings"]
    }
    mapped = []
    exceptions = []
    for output in snapshot["visible_card_outputs"]:
        direct = output.get("event_set_ref")
        if isinstance(direct, dict) and isinstance(direct.get("set_id"), str):
            matches = [
                row
                for row in versions.get(output["recording_id"], [])
                if row["node_id"] == direct.get("set_id")
                and row["revision_id"] == direct.get("version")
                and row["content_sha256"] == direct.get("content_sha256")
            ]
            if len(matches) == 1:
                mapped.append({**output, "converted_parent": direct, "match": "direct-reference"})
            else:
                exceptions.append(
                    {
                        "recording_id": output["recording_id"],
                        "output_node_id": output["node_id"],
                        "output_revision_id": output["revision_id"],
                        "output_sha256": output["file_sha256"],
                        "legacy_event_revision_id": None,
                        "reason": "missing" if not matches else "ambiguous",
                        "candidate_count": len(matches),
                    }
                )
            continue
        legacy_id = output.get("event_revision_id")
        candidates = [
            row
            for row in legacy_rows.get(output["recording_id"], [])
            if isinstance(legacy_id, str)
            and bool(legacy_id)
            and row.get("legacy_revision_id") == legacy_id
        ]
        targets = versions.get(output["recording_id"], [])
        exact = [
            (candidate, target)
            for candidate in candidates
            for target in targets
            if target["node_id"] == candidate["node_id"]
            and target["revision_id"] == candidate["revision_id"]
            and target["content_sha256"] == candidate["content_sha256"]
        ]
        row = {
            "recording_id": output["recording_id"],
            "output_node_id": output["node_id"],
            "output_revision_id": output["revision_id"],
            "output_sha256": output["file_sha256"],
            "legacy_event_revision_id": legacy_id,
        }
        if len(candidates) == 1 and len(exact) == 1:
            candidate, target = exact[0]
            mapped.append(
                {
                    **row,
                    "converted_parent": {
                        "set_id": candidate["node_id"],
                        "version": candidate["revision_id"],
                        "content_sha256": target["content_sha256"],
                    },
                    "match": "unique-provenance-digest",
                }
            )
        else:
            exceptions.append(
                {
                    **row,
                    "reason": (
                        "missing"
                        if not candidates
                        else "ambiguous"
                        if len(candidates) > 1
                        else "digest-mismatch"
                    ),
                    "candidate_count": len(candidates),
                }
            )
    return {"mapped": mapped, "exceptions": exceptions}


def _snapshot_node(path: Path, manifest: dict[str, Any], content_type: str) -> dict[str, Any]:
    node_id = manifest["node_id"]
    revisions = []
    for revision_path in sorted((path.parent / "revisions").glob("*/revision.json")):
        revision = _read_json(revision_path)
        metadata = revision.get("metadata", {})
        content = revision.get("content", {})
        row = {
            "recording_id": manifest["source"]["recording_id"],
            "node_id": node_id,
            "revision_id": revision_path.parent.name,
            "file_sha256": _sha256_file(revision_path),
            "content_sha256": revision.get("content_sha256"),
        }
        if content_type == "events":
            row["legacy_revision_id"] = metadata.get("legacy_revision_id")
            row["event_count"] = len(content.get("events", []))
        else:
            coverage = metadata.get("coverage", {})
            row["event_revision_id"] = coverage.get("event_revision_id")
            row["event_set_ref"] = coverage.get("event_set_ref")
        revisions.append(row)
    return {
        "node_id": node_id,
        "content_type": content_type,
        "manifest": _file_fact(path),
        "revisions": revisions,
    }


def _import_missing_bundles(
    bundle_root: Path, recordings_root: Path, snapshot: dict[str, Any]
) -> None:
    store = RecordingFolderStore(recordings_root)
    for row in snapshot["recordings"]:
        recording_id = row["recording_id"]
        existing = store.get(recording_id)
        source = row["bundle"]["source_media"]
        if existing is not None:
            if existing.source.get("sha256") != source["sha256"]:
                raise RolloutError(f"existing recording source differs: {recording_id}")
            continue
        store.publish_bundle(bundle_root / recording_id, recording_id=recording_id)


def _copy_existing_roots(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    store = RecordingFolderStore(source)
    for root in store.list():
        shutil.copytree(store.recording_path(root.recording_id), destination / root.recording_id)


def _event_version_keys(recordings_root: Path) -> set[str]:
    result = set()
    if not recordings_root.exists():
        return result
    for metadata in recordings_root.glob("*/event-sets/*/versions/*/event-set.json"):
        result.add(f"{metadata.parents[4].name}/{metadata.parents[2].name}@{metadata.parent.name}")
    return result


def _verify_snapshot(snapshot: dict[str, Any]) -> None:
    expected = snapshot.get("snapshot_sha256")
    payload = {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    actual = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    if expected != actual:
        raise RolloutError("frozen corpus snapshot digest is invalid")
    current = build_snapshot(
        bundle_root=Path(snapshot["bundle_root"]),
        recordings_root=Path(snapshot["recordings_root"]),
        operations_root=Path(snapshot["operations_root"]),
    )
    if current["snapshot_sha256"] != expected:
        raise RolloutError("live corpus inputs changed after the frozen snapshot")


def _file_fact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": _sha256_file(path),
        "byte_length": path.stat().st_size,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        entries.append([path.relative_to(root).as_posix(), _sha256_file(path)])
    return hashlib.sha256(canonical_json_bytes(entries)).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise RolloutError(f"invalid JSON object: {path}")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(value))
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "rehearse", "activate"))
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--recordings-root", type=Path, required=True)
    parser.add_argument("--operations-root", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--disposable-root", type=Path)
    parser.add_argument("--rehearsal-receipt", type=Path)
    parser.add_argument("--recovery-path", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "snapshot":
        value = build_snapshot(
            bundle_root=args.bundle_root,
            recordings_root=args.recordings_root,
            operations_root=args.operations_root,
        )
        _atomic_json(args.snapshot, value)
        value = {
            "schema_version": "0124-event-corpus-snapshot-receipt/v1",
            "snapshot_sha256": value["snapshot_sha256"],
            "recording_count": len(value["recordings"]),
            "output_count": len(value["visible_card_outputs"]),
            "snapshot_path": str(args.snapshot.resolve()),
        }
    elif args.action == "rehearse":
        if args.disposable_root is None:
            parser.error("--disposable-root is required for rehearsal")
        snapshot = _read_json(args.snapshot)
        value = rehearse_snapshot(
            snapshot=snapshot,
            disposable_root=args.disposable_root,
            existing_recordings_root=args.recordings_root,
        )
    else:
        if args.rehearsal_receipt is None or args.recovery_path is None:
            parser.error("--rehearsal-receipt and --recovery-path are required for activation")
        value = activate_snapshot(
            snapshot=_read_json(args.snapshot),
            rehearsal_receipt=_read_json(args.rehearsal_receipt),
            recovery_path=args.recovery_path,
        )
    _atomic_json(args.receipt, value)
    print(
        json.dumps(
            {
                "action": args.action,
                "snapshot_sha256": value.get("snapshot_sha256"),
                "output": str(args.receipt),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["RolloutError", "activate_snapshot", "build_snapshot", "rehearse_snapshot"]
