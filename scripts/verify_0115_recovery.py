"""Verify the bounded 0115 recovery evidence without changing retained data."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import stat
from collections import Counter
from pathlib import Path
from typing import Any

from dokodetector_backend.lineage_migration_apply import _verify_package


def _stable_digest(path: Path) -> tuple[int, str]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"expected a regular file: {path}")
    digest = hashlib.sha256()
    size = 0
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(stream.fileno())
    end = path.lstat()

    def identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    if identity(before) != identity(opened) or identity(opened) != identity(after):
        raise ValueError(f"file changed while hashing: {path}")
    if identity(after) != identity(end) or size != before.st_size:
        raise ValueError(f"file changed while hashing: {path}")
    return size, digest.hexdigest()


def _tree_manifest(root: Path) -> dict[str, Any]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"expected a non-symlink directory: {root}")
    rows: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink in retained recovery tree: {path}")
        if path.is_file():
            size, digest = _stable_digest(path)
            rows.append((path.relative_to(root).as_posix(), size, digest))
        elif not path.is_dir():
            raise ValueError(f"unsupported recovery entry: {path}")
    canonical = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    return {
        "files": len(rows),
        "bytes": sum(row[1] for row in rows),
        "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def _verify_retained_records(
    stage: Path, nodes: Path, manifest: dict[str, Any]
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    file_count = 0
    byte_count = 0
    for resource in manifest["resources"]:
        kind = resource["kind"]
        if kind not in {"maintained_draft", "independent_review", "calibration_draft"}:
            continue
        key = hashlib.sha256(f"{kind}/{resource['old_id']}".encode()).hexdigest()
        record_path = nodes / ".migrated-records" / kind / f"{key}.json"
        record = json.loads(record_path.read_bytes())
        if record.get("old_id") != resource["old_id"]:
            raise ValueError(f"retained record identity mismatch: {record_path}")
        if record.get("snapshot_sha256") != manifest["snapshot_sha256"]:
            raise ValueError(f"retained record snapshot mismatch: {record_path}")
        for file_record in resource["files"]:
            relative = file_record["path"]
            embedded = record["files"].get(relative)
            staged = stage / "evidence" / resource["old_root_id"] / relative
            if embedded is None:
                raise ValueError(f"retained file is absent from node store: {relative}")
            raw = base64.b64decode(embedded["base64"], validate=True)
            if (
                len(raw) != embedded["byte_length"]
                or hashlib.sha256(raw).hexdigest() != embedded["sha256"]
            ):
                raise ValueError(
                    f"embedded retained bytes failed validation: {relative}"
                )
            size, digest = _stable_digest(staged)
            if size != file_record["byte_length"] or digest != file_record["sha256"]:
                raise ValueError(f"staged retained bytes failed validation: {relative}")
            if raw != staged.read_bytes():
                raise ValueError(f"staged and active retained bytes differ: {relative}")
            file_count += 1
            byte_count += len(raw)
        counts[kind] += 1
    return {
        "resources": dict(sorted(counts.items())),
        "resource_total": sum(counts.values()),
        "files_exact": file_count,
        "embedded_bytes": byte_count,
    }


def verify(data_root: Path, runtime_root: Path) -> dict[str, Any]:
    recovery_root = data_root / "operations-recovery" / "0108-m10-20261105"
    stage = recovery_root / "migration-stage-accepted-loss"
    package = json.loads((stage / "migration.json").read_bytes())
    _verify_package(stage, package)
    nodes = data_root / "operations" / "pipeline-nodes"
    retained_records = _verify_retained_records(stage, nodes, package)
    return {
        "schema_version": "0115-recovery-validation/v1",
        "snapshot_sha256": package["snapshot_sha256"],
        "plan_sha256": package["plan_sha256"],
        "migration_package": {
            "resources": package["resource_count"],
            "files": package["file_count"],
            "activation_ready": package["activation_ready"],
        },
        "active_pipeline_nodes": _tree_manifest(nodes),
        "retained_records": retained_records,
        "representative_recording": _tree_manifest(
            data_root / "intake" / "recordings" / "cardeventnet-IMG_0637"
        ),
        "raw_model_source": _tree_manifest(
            data_root / "models" / "dinov3-vits16-pretrain-lvd1689m"
        ),
        "runtime_model_bundle": _tree_manifest(
            runtime_root / "dinov3-identity-0088" / "bundles" / "224-cls"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(
        args.data_root.expanduser().resolve(), args.runtime_root.expanduser().resolve()
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key != "active_pipeline_nodes"
            }
        )
    )


if __name__ == "__main__":
    main()
