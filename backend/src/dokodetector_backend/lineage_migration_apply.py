"""Apply a lineage inventory to an isolated, verified staging package."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _safe_relative(value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("invalid relative path")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("invalid relative path")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError("invalid relative path")
    return Path(*path.parts)


def _sha256(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _validate_plan(plan: dict[str, Any]) -> None:
    if plan.get("schema_version") != "lineage-migration-inventory/v1":
        raise ValueError("unsupported inventory plan")
    if not isinstance(plan.get("snapshot_sha256"), str) or len(plan["snapshot_sha256"]) != 64:
        raise ValueError("invalid snapshot digest")
    if not isinstance(plan.get("files"), list) or not isinstance(plan.get("resources"), list):
        raise ValueError("invalid inventory contents")
    if not isinstance(plan.get("sealed_artifacts"), list):
        raise ValueError("invalid sealed-artifact declarations")
    if not isinstance(plan.get("reference_only_root_ids", []), list):
        raise ValueError("invalid reference-only roots")
    if any(
        not isinstance(root_id, str) or not root_id
        for root_id in plan.get("reference_only_root_ids", [])
    ):
        raise ValueError("invalid reference-only root ID")


def _safe_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in value
        )
    ):
        raise ValueError("invalid migration ID")
    return value


def _verify_package(root: Path, manifest: dict[str, Any]) -> None:
    files = manifest["files"]
    resources = manifest["resources"]
    reference_only = set(manifest.get("reference_only_root_ids", []))
    if len(files) != manifest["file_count"] or len(resources) != manifest["resource_count"]:
        raise ValueError("staged counts do not match manifest")
    for item in files:
        if item.get("external_reference") is True:
            if item["root_id"] not in reference_only:
                raise ValueError("external artifact root is not declared reference-only")
            if "staged_path" in item:
                raise ValueError("external artifact must not name a staged path")
            continue
        relative = _safe_relative(item["staged_path"])
        size, digest = _sha256(root / relative)
        if (size, digest) != (item["byte_length"], item["sha256"]):
            raise ValueError(f"staged source bytes do not match: {item['staged_path']}")
    ids = {item["new_id"] for item in resources}
    by_id = {item["new_id"]: item for item in resources}
    for resource in resources:
        resource_path = root / "resources" / f"{resource['new_id']}.json"
        if not resource_path.is_file() or json.loads(resource_path.read_bytes()) != resource:
            raise ValueError("staged resource record does not match manifest")
        for reference in resource["references"]:
            target = reference.get("target_id")
            if target is not None and target not in ids:
                raise ValueError("reference points to an unmapped resource")
            embedded_evidence = reference.get("embedded_evidence_id")
            if embedded_evidence is not None and (
                embedded_evidence not in by_id
                or by_id[embedded_evidence].get("kind") != "pipeline_revision"
            ):
                raise ValueError("embedded calibration evidence points to an invalid revision")
            target_revision = reference.get("target_revision_id")
            if target_revision is not None and not any(
                candidate.get("new_revision_id") == target_revision for candidate in resources
            ):
                raise ValueError("reference points to an unmapped revision")


def apply_plan(
    plan: dict[str, Any], destination: Path | str, roots: dict[str, Path | str]
) -> dict[str, Any]:
    """Create an isolated staging package from the exact inventory snapshot.

    The destination is a migration artifact, not an active application store. Existing identical
    output is returned as an idempotent retry; a different package is never overwritten.
    """
    _validate_plan(plan)
    target = Path(destination).expanduser().absolute()
    normalized_roots = {key: Path(value).expanduser().absolute() for key, value in roots.items()}
    for root_id in normalized_roots:
        _safe_id(root_id)
    for resource in plan["resources"]:
        _safe_id(resource["new_id"])
    target_resolved = target.resolve(strict=False)
    for root in normalized_roots.values():
        resolved_root = root.resolve()
        if target_resolved == resolved_root or resolved_root in target_resolved.parents:
            raise ValueError("destination must be outside all source roots")
    if {item["root_id"] for item in plan["files"]} - set(normalized_roots):
        raise ValueError("apply roots do not match the inventory")
    reference_only = set(plan.get("reference_only_root_ids", []))
    if reference_only - set(normalized_roots):
        raise ValueError("reference-only root is not declared")
    from dokodetector_backend.lineage_migration_inventory import _files

    sealed_by_root: dict[str, set[str]] = {key: set() for key in normalized_roots}
    for item in plan["sealed_artifacts"]:
        sealed_by_root[item["root_id"]].add(item["relative_path"])
    expected = {
        root_id: {
            item["path"]: (item["byte_length"], item["sha256"])
            for item in plan["files"]
            if item["root_id"] == root_id
        }
        for root_id in normalized_roots
    }
    for root_id, root in normalized_roots.items():
        if root.is_symlink() or not root.is_dir() or root.resolve() != root:
            raise ValueError("apply root must be an existing non-symlink directory")
        if _files(root, sealed_by_root[root_id]) != expected[root_id]:
            raise ValueError("source snapshot changed since inventory")
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_dir():
            raise ValueError("destination exists and is not a migration package")
        existing_path = target / "migration.json"
        if not existing_path.is_file():
            raise ValueError("destination already exists")
        existing = _read_object(existing_path)
        if existing.get("snapshot_sha256") != plan["snapshot_sha256"]:
            raise ValueError("destination contains a different snapshot")
        if existing.get("reference_only_root_ids", []) != sorted(reference_only):
            raise ValueError("destination uses a different external-reference policy")
        _verify_package(target, existing)
        return existing

    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=parent))
    try:
        files = []
        for item in plan["files"]:
            root_id = item["root_id"]
            if root_id not in normalized_roots:
                raise ValueError("file refers to an undeclared source root")
            relative = _safe_relative(item["path"])
            source = normalized_roots[root_id] / relative
            if source.is_symlink() or not source.is_file():
                raise ValueError(f"source file is missing or unsafe: {item['path']}")
            size, digest = _sha256(source)
            if (size, digest) != (item["byte_length"], item["sha256"]):
                raise ValueError(f"source snapshot changed: {item['path']}")
            if root_id in reference_only:
                files.append(
                    {
                        "root_id": root_id,
                        "path": item["path"],
                        "external_reference": True,
                        "byte_length": size,
                        "sha256": digest,
                    }
                )
            else:
                if item.get("external_reference") is True:
                    raise ValueError("external artifact root is not declared reference-only")
                staged_relative = Path("evidence") / root_id / relative
                staged_file = staging / staged_relative
                staged_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, staged_file)
                files.append(
                    {
                        "root_id": root_id,
                        "path": item["path"],
                        "staged_path": staged_relative.as_posix(),
                        "byte_length": size,
                        "sha256": digest,
                    }
                )

        resources = []
        resource_root = staging / "resources"
        resource_root.mkdir()
        for item in plan["resources"]:
            converted = {
                "schema_version": "lineage-migration-resource/v1",
                "kind": item["kind"],
                "old_root_id": item["root_id"],
                "old_id": item["old_id"],
                "relative_identity": item["relative_identity"],
                "new_id": item["new_id"],
                "new_revision_id": item.get("new_revision_id"),
                "content_type": item.get("content_type"),
                "content_schema": item.get("content_schema"),
                "recording_id": item.get("recording_id"),
                "content_sha256": item.get("content_sha256"),
                "unknown_history": item.get("unknown_history", "not_recorded"),
                "references": item["references"],
                "files": [
                    {
                        "path": f["path"],
                        "byte_length": f["byte_length"],
                        "sha256": f["sha256"],
                    }
                    for f in item["files"]
                ],
            }
            (resource_root / f"{item['new_id']}.json").write_bytes(_json_bytes(converted))
            resources.append(converted)

        for root_id, root in normalized_roots.items():
            if _files(root, sealed_by_root[root_id]) != expected[root_id]:
                raise ValueError("source snapshot changed during migration")

        manifest = {
            "schema_version": "lineage-migration-stage/v1",
            "snapshot_sha256": plan["snapshot_sha256"],
            "activation_ready": plan["activation_ready"],
            "conflicts": plan["conflicts"],
            "uncertainties": plan["uncertainties"],
            "sealed_artifacts": plan["sealed_artifacts"],
            "reference_only_root_ids": sorted(reference_only),
            "file_count": len(files),
            "resource_count": len(resources),
            "files": files,
            "resources": resources,
        }
        _verify_package(staging, manifest)
        (staging / "migration.json").write_bytes(_json_bytes(manifest))
        staging_fd = os.open(staging, os.O_RDONLY)
        try:
            os.fsync(staging_fd)
        finally:
            os.close(staging_fd)
        os.rename(staging, target)
        parent_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        return manifest
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main() -> None:
    """Apply a saved inventory plan into a separate staging package."""
    import argparse

    parser = argparse.ArgumentParser(description="Apply a lineage inventory to a staging root")
    parser.add_argument("config", type=Path, help="inventory config JSON with source roots")
    parser.add_argument("plan", type=Path, help="lineage migration inventory JSON")
    parser.add_argument("destination", type=Path, help="new staging package path")
    args = parser.parse_args()
    config = _read_object(args.config)
    plan = _read_object(args.plan)
    apply_plan(plan, args.destination, config.get("roots", {}))


if __name__ == "__main__":
    main()
