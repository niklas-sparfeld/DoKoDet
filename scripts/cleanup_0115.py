"""Plan and safely apply one bounded 0115 cleanup manifest."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "0115-cleanup-application/v1"
CHUNK_SIZE = 1024 * 1024


class CleanupError(ValueError):
    """The plan or filesystem is not safe to apply."""


def _digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _relative_path(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CleanupError(f"invalid {label}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise CleanupError(f"unsafe {label}: {value}")
    return path


def _contained(
    root: Path, relative: PurePosixPath, *, allow_missing: bool = False
) -> Path:
    """Resolve a relative path while rejecting every symlink component."""
    cursor = root
    for index, part in enumerate(relative.parts):
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            if allow_missing:
                continue
            raise CleanupError(f"missing path: {relative}") from None
        if stat.S_ISLNK(info.st_mode):
            raise CleanupError(f"symlink path rejected: {relative}")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise CleanupError(f"non-directory path component: {relative}")
    if not cursor.resolve(strict=not allow_missing).is_relative_to(root):
        raise CleanupError(f"path escapes selected root: {relative}")
    return cursor


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise CleanupError(f"expected a regular JSON file: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CleanupError(f"invalid JSON file {path}: {error}") from error
    if not isinstance(value, dict):
        raise CleanupError(f"expected a JSON object: {path}")
    return value, raw


def _stable_file(
    path: Path, *, require_single_link: bool = True
) -> tuple[int, str, tuple[int, int, int, int, int, int]]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise CleanupError(f"expected a regular file: {path}")
    if require_single_link and before.st_nlink != 1:
        raise CleanupError(f"candidate must be a single-link regular file: {path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    digest = hashlib.sha256()
    size = 0
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        for block in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(block)
            size += len(block)
        after = os.fstat(stream.fileno())
    end = path.lstat()
    if not (
        _identity(before) == _identity(opened) == _identity(after) == _identity(end)
    ):
        raise CleanupError(f"file identity changed while hashing: {path}")
    if size != before.st_size:
        raise CleanupError(f"file size changed while hashing: {path}")
    return size, digest.hexdigest(), _identity(before)


def _git_revision(repo: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _require_manifest_authority(manifest: dict[str, Any]) -> None:
    if manifest.get("deletion_authorized") is not True:
        raise CleanupError("manifest does not explicitly authorize deletion")
    if manifest.get("references_complete") is not True:
        raise CleanupError("manifest does not declare a complete reference check")
    if manifest.get("unknowns"):
        raise CleanupError("manifest contains unknown references")
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list) or any(
        not isinstance(item, dict) or item.get("unknown_references")
        for item in candidates
    ):
        raise CleanupError("manifest contains unknown candidate references")


def _candidate_rows(
    manifest: dict[str, Any],
    repo: Path,
    cleanup_root: PurePosixPath,
    *,
    require_authorization: bool = False,
    recovery_rows: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list):
        raise CleanupError("manifest candidates must be a list")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            raise CleanupError("candidate must be an object")
        relative = _relative_path(item.get("path"), "candidate path")
        if cleanup_root not in relative.parents:
            continue
        key = relative.as_posix()
        if key in seen:
            raise CleanupError(f"duplicate candidate path: {key}")
        seen.add(key)
        if require_authorization and item.get("authorization") != "authorized":
            raise CleanupError(f"candidate is not explicitly authorized: {key}")
        expected_size = item.get("bytes")
        expected_digest = item.get("sha256")
        if not isinstance(expected_size, int) or expected_size < 0:
            raise CleanupError(f"invalid candidate size: {key}")
        if not isinstance(expected_digest, str) or len(expected_digest) != 64:
            raise CleanupError(f"invalid candidate digest: {key}")
        references = item.get("references")
        if references is None and isinstance(item.get("intake_path"), str):
            references = [
                {
                    "path": item["intake_path"],
                    "bytes": expected_size,
                    "sha256": expected_digest,
                }
            ]
        if not isinstance(references, list):
            raise CleanupError(f"candidate references are not declared: {key}")
        reference_rows = []
        for reference in references:
            if not isinstance(reference, dict):
                raise CleanupError(f"invalid declared reference for {key}")
            reference_path = _relative_path(reference.get("path"), "reference path")
            if cleanup_root in reference_path.parents:
                raise CleanupError(
                    f"protected dependency is inside cleanup root: {reference_path}"
                )
            dependency = _contained(repo, reference_path)
            size, digest, identity = _stable_file(dependency, require_single_link=False)
            if size != reference.get("bytes") or digest != reference.get("sha256"):
                raise CleanupError(f"protected dependency changed: {reference_path}")
            reference_rows.append(
                {
                    "path": reference_path.as_posix(),
                    "bytes": size,
                    "sha256": digest,
                    "identity": list(identity),
                }
            )
        candidate_path = _contained(repo, relative, allow_missing=True)
        if not candidate_path.exists() and recovery_rows and key in recovery_rows:
            recovered = recovery_rows[key]
            size, digest, identity = (
                expected_size,
                expected_digest,
                recovered["identity"],
            )
        else:
            size, digest, identity = _stable_file(candidate_path)
            if size != expected_size or digest != expected_digest:
                raise CleanupError(f"candidate differs from frozen manifest: {key}")
        rows.append(
            {
                "path": key,
                "bytes": size,
                "sha256": digest,
                "identity": list(identity),
                "references": reference_rows,
            }
        )
    if not rows:
        raise CleanupError("manifest has no candidates under the selected root")
    return sorted(rows, key=lambda row: row["path"])


def _atomic_json(root: Path, path: Path, document: dict[str, Any]) -> None:
    parent = path.parent
    if not parent.is_relative_to(root):
        raise CleanupError(f"output directory escapes selected root: {parent}")
    relative_parent = parent.relative_to(root)
    cursor = root
    for part in relative_parent.parts:
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            cursor.mkdir()
            _fsync_directory(cursor.parent)
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise CleanupError(f"unsafe output directory: {cursor}")
    if path.is_symlink():
        raise CleanupError(f"symlink output rejected: {path}")
    payload = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=".cleanup-", dir=parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _assert_no_open_files(
    root: Path, *, ignored_paths: set[Path] | None = None
) -> None:
    executable = shutil.which("lsof")
    if executable is None:
        raise CleanupError("cannot check current open-file state; lsof is required")
    result = subprocess.run(
        [executable, "-F0n", "+D", str(root)], capture_output=True, check=False
    )
    if result.returncode not in {0, 1} or result.stderr.strip():
        raise CleanupError(
            f"open-file check failed: {result.stderr.decode(errors='replace').strip()}"
        )
    ignored = {path.resolve() for path in ignored_paths or set()}
    open_paths = [
        Path(field[1:].decode(errors="surrogateescape"))
        for field in result.stdout.split(b"\0")
        if field.startswith(b"n")
    ]
    if any(path.resolve() not in ignored for path in open_paths):
        raise CleanupError("open files exist under selected cleanup root")


def _acquire_apply_lock(root: Path) -> tuple[int, Path]:
    lock_path = root / ".cleanup.apply.lock"
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise CleanupError("cannot safely open apply lock without O_NOFOLLOW")
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | nofollow,
            0o600,
        )
    except OSError as error:
        raise CleanupError(f"cannot open apply lock: {error}") from error
    opened = os.fstat(descriptor)
    try:
        current = lock_path.lstat()
    except OSError:
        os.close(descriptor)
        raise CleanupError("apply lock path changed while opening") from None
    if (
        not stat.S_ISREG(opened.st_mode)
        or stat.S_ISLNK(current.st_mode)
        or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
    ):
        os.close(descriptor)
        raise CleanupError("apply lock is not a stable regular file")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(descriptor)
        raise CleanupError("another cleanup apply is active for this root") from error
    return descriptor, lock_path


def _plan(args: argparse.Namespace) -> Path:
    repo = args.repo_root.resolve(strict=True)
    if not repo.is_dir():
        raise CleanupError("repository root must be a directory")
    manifest_path = args.manifest.resolve(strict=True)
    if not manifest_path.is_relative_to(repo):
        raise CleanupError("source manifest must be inside repository root")
    manifest, raw = _read_json(manifest_path)
    if manifest.get("schema_version") != "0115-cleanup-plan/v1":
        raise CleanupError("unsupported source manifest schema")
    cleanup_root = _relative_path(args.cleanup_root, "cleanup root")
    root = _contained(repo, cleanup_root)
    if not root.is_dir():
        raise CleanupError("selected cleanup root must be a directory")
    rows = _candidate_rows(manifest, repo, cleanup_root)
    source_digest = _digest_bytes(raw)
    plan: dict[str, Any] = {
        "schema_version": SCHEMA,
        "source_manifest": manifest_path.relative_to(repo).as_posix(),
        "source_manifest_sha256": source_digest,
        "source_revision": _git_revision(repo),
        "cleanup_root": cleanup_root.as_posix(),
        "root_identity": [root.stat().st_dev, root.stat().st_ino],
        "candidate_count": len(rows),
        "candidates": rows,
        "retained_roots": [
            item.get("path")
            for item in manifest.get("retained_paths", [])
            if isinstance(item, dict)
        ],
        "apply_permitted": (
            manifest.get("deletion_authorized") is True
            and manifest.get("references_complete") is True
            and not manifest.get("unknowns")
            and all(
                item.get("authorization") == "authorized"
                for item in manifest.get("candidates", [])
                if isinstance(item, dict)
                and cleanup_root.as_posix() in str(item.get("path", ""))
            )
        ),
    }
    plan_id = _digest_bytes(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    )
    plan["plan_sha256"] = plan_id
    default_output = cleanup_root / ".cleanup-plans" / f"{plan_id}.json"
    output_relative = (
        cleanup_root / _relative_path(args.output, "plan output")
        if args.output
        else default_output
    )
    output = _contained(repo, output_relative, allow_missing=True)
    if not output.is_relative_to(root):
        raise CleanupError("plan output must be inside selected cleanup root")
    _atomic_json(root, output, plan)
    print(
        json.dumps(
            {
                "plan": output_relative.as_posix(),
                "candidates": len(rows),
                "apply_permitted": plan["apply_permitted"],
            }
        )
    )
    return output


def _load_plan(
    repo: Path, plan_relative_value: str
) -> tuple[dict[str, Any], Path, dict[str, Any] | None]:
    plan_relative = _relative_path(plan_relative_value, "plan path")
    path = _contained(repo, plan_relative)
    plan, _ = _read_json(path)
    if plan.get("schema_version") != SCHEMA:
        raise CleanupError("unsupported plan schema")
    claimed = plan.get("plan_sha256")
    body = {key: value for key, value in plan.items() if key != "plan_sha256"}
    actual = _digest_bytes(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    )
    if claimed != actual:
        raise CleanupError("plan digest mismatch")
    root_relative = _relative_path(plan.get("cleanup_root"), "cleanup root")
    root = _contained(repo, root_relative)
    if not root.is_dir() or [root.stat().st_dev, root.stat().st_ino] != plan.get(
        "root_identity"
    ):
        raise CleanupError("selected cleanup root identity changed")
    source_path = _contained(
        repo, _relative_path(plan.get("source_manifest"), "manifest path")
    )
    manifest, raw = _read_json(source_path)
    if _digest_bytes(raw) != plan.get("source_manifest_sha256"):
        raise CleanupError("source manifest changed since planning")
    planned_revision = plan.get("source_revision")
    if planned_revision is not None and _git_revision(repo) != planned_revision:
        raise CleanupError("repository revision changed since planning")
    _require_manifest_authority(manifest)
    receipt_relative = root_relative / ".cleanup-receipts" / f"{claimed}.json"
    receipt_path = _contained(repo, receipt_relative, allow_missing=True)
    recovery_rows: dict[str, dict[str, Any]] = {}
    receipt = None
    if receipt_path.exists():
        receipt, _ = _read_json(receipt_path)
        recovery_rows = _validate_receipt(receipt, plan, repo, root)
    expected = _candidate_rows(
        manifest,
        repo,
        root_relative,
        require_authorization=True,
        recovery_rows=recovery_rows,
    )
    if expected != plan.get("candidates"):
        raise CleanupError("candidate paths or identities changed since planning")
    return plan, root, receipt


def _validate_receipt(
    receipt: dict[str, Any], plan: dict[str, Any], repo: Path, root: Path
) -> dict[str, dict[str, Any]]:
    """Check that receipt progress matches this plan and current candidate presence."""
    if (
        receipt.get("schema_version") != "0115-cleanup-receipt/v1"
        or receipt.get("plan_sha256") != plan["plan_sha256"]
        or receipt.get("source_manifest_sha256") != plan["source_manifest_sha256"]
        or receipt.get("source_revision") != plan["source_revision"]
        or receipt.get("cleanup_root") != plan["cleanup_root"]
        or receipt.get("retained_roots") != plan["retained_roots"]
        or receipt.get("action") != "unlink exact regular files"
    ):
        raise CleanupError("receipt metadata does not match plan")
    receipt_status = receipt.get("status")
    if receipt_status not in {"in_progress", "complete"}:
        raise CleanupError("invalid receipt status")

    entries = receipt.get("candidates")
    planned = plan.get("candidates")
    if (
        not isinstance(entries, list)
        or not isinstance(planned, list)
        or len(entries) != len(planned)
    ):
        raise CleanupError("receipt candidate list does not match plan")

    recovery_rows: dict[str, dict[str, Any]] = {}
    statuses: list[str] = []
    for entry, candidate in zip(entries, planned, strict=True):
        if not isinstance(entry, dict) or set(entry) != {
            "path",
            "expected_bytes",
            "expected_sha256",
            "planned_identity",
            "status",
        }:
            raise CleanupError("invalid receipt candidate entry")
        if (
            entry.get("path") != candidate["path"]
            or entry.get("expected_bytes") != candidate["bytes"]
            or entry.get("expected_sha256") != candidate["sha256"]
            or entry.get("planned_identity") != candidate["identity"]
        ):
            raise CleanupError("receipt candidate list does not match plan")
        status = entry.get("status")
        if status not in {"pending", "deleting", "removed"}:
            raise CleanupError("invalid receipt candidate status")
        statuses.append(status)
        candidate_path = _contained(
            repo,
            _relative_path(candidate["path"], "candidate path"),
            allow_missing=True,
        )
        exists = candidate_path.exists()
        if status == "pending" and not exists:
            raise CleanupError(f"pending candidate is absent: {candidate['path']}")
        if status == "removed" and exists:
            raise CleanupError(
                f"receipt marks an existing candidate removed: {candidate['path']}"
            )
        if not exists and status in {"deleting", "removed"}:
            recovery_rows[candidate["path"]] = candidate
    if receipt_status == "complete" and (
        any(status != "removed" for status in statuses)
        or len(recovery_rows) != len(planned)
    ):
        raise CleanupError("complete receipt does not match candidate state")

    observed = receipt.get("observed")
    if not isinstance(observed, list):
        raise CleanupError("invalid receipt observations")
    allowed_paths = {candidate["path"] for candidate in planned}
    observed_paths: set[str] = set()
    for item in observed:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "result"}
            or item.get("path") not in allowed_paths
            or item.get("result") not in {"removed", "removed_after_interruption"}
            or item["path"] in observed_paths
        ):
            raise CleanupError("invalid receipt observation")
        position = next(
            i
            for i, candidate in enumerate(planned)
            if candidate["path"] == item["path"]
        )
        if statuses[position] != "removed":
            raise CleanupError("receipt observation conflicts with candidate status")
        observed_paths.add(item["path"])
    for candidate, status in zip(planned, statuses, strict=True):
        if (status == "removed") != (candidate["path"] in observed_paths):
            raise CleanupError("receipt observation is missing for removed candidate")
    return recovery_rows


def _apply(args: argparse.Namespace) -> None:
    repo = args.repo_root.resolve(strict=True)
    plan, root, _ = _load_plan(repo, args.plan)
    if not plan.get("apply_permitted"):
        raise CleanupError("plan is dry-run only; manifest does not authorize apply")
    lock_descriptor, lock_path = _acquire_apply_lock(root)
    try:
        # Reload under the root lock so apply consumes the receipt it just validated.
        plan, root, receipt = _load_plan(repo, args.plan)
        if not plan.get("apply_permitted"):
            raise CleanupError(
                "plan is dry-run only; manifest does not authorize apply"
            )
        _apply_validated(repo, plan, root, receipt, lock_path)
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)


def _apply_validated(
    repo: Path,
    plan: dict[str, Any],
    root: Path,
    receipt: dict[str, Any] | None,
    lock_path: Path,
) -> None:
    plan_id = plan["plan_sha256"]
    receipt_relative = (
        PurePosixPath(plan["cleanup_root"]) / ".cleanup-receipts" / f"{plan_id}.json"
    )
    receipt_path = _contained(repo, receipt_relative, allow_missing=True)
    if not receipt_path.is_relative_to(root):
        raise CleanupError("receipt path escaped selected root")
    if receipt is None:
        _assert_no_open_files(root, ignored_paths={lock_path})
        receipt = {
            "schema_version": "0115-cleanup-receipt/v1",
            "status": "in_progress",
            "plan_sha256": plan_id,
            "source_manifest_sha256": plan["source_manifest_sha256"],
            "source_revision": plan["source_revision"],
            "cleanup_root": plan["cleanup_root"],
            "retained_roots": plan["retained_roots"],
            "action": "unlink exact regular files",
            "candidates": [
                {
                    "path": item["path"],
                    "expected_bytes": item["bytes"],
                    "expected_sha256": item["sha256"],
                    "planned_identity": item["identity"],
                    "status": "pending",
                }
                for item in plan["candidates"]
            ],
            "observed": [],
        }
        _atomic_json(root, receipt_path, receipt)

    if all(item["status"] == "removed" for item in receipt["candidates"]):
        if receipt.get("status") != "complete":
            _assert_no_open_files(root, ignored_paths={lock_path})
            receipt["status"] = "complete"
            _atomic_json(root, receipt_path, receipt)
        print(
            json.dumps(
                {
                    "receipt": receipt_relative.as_posix(),
                    "status": "complete",
                    "removed": len(receipt["candidates"]),
                }
            )
        )
        return
    _assert_no_open_files(root, ignored_paths={lock_path})
    for receipt_item, candidate in zip(
        receipt["candidates"], plan["candidates"], strict=True
    ):
        if receipt_item["status"] == "removed":
            continue
        candidate_relative = _relative_path(candidate["path"], "candidate path")
        path = _contained(repo, candidate_relative, allow_missing=True)
        if not path.exists():
            if receipt_item["status"] != "deleting":
                raise CleanupError(
                    f"candidate disappeared before apply: {candidate['path']}"
                )
            receipt_item["status"] = "removed"
            receipt["observed"].append(
                {"path": candidate["path"], "result": "removed_after_interruption"}
            )
            _atomic_json(root, receipt_path, receipt)
            continue
        size, digest, identity = _stable_file(path)
        if (
            size != candidate["bytes"]
            or digest != candidate["sha256"]
            or list(identity) != candidate["identity"]
        ):
            raise CleanupError(f"candidate changed since planning: {candidate['path']}")
        for reference in candidate["references"]:
            dependency = _contained(
                repo, _relative_path(reference["path"], "reference path")
            )
            ref_size, ref_digest, ref_identity = _stable_file(
                dependency, require_single_link=False
            )
            if (
                ref_size != reference["bytes"]
                or ref_digest != reference["sha256"]
                or list(ref_identity) != reference["identity"]
            ):
                raise CleanupError(f"protected dependency changed: {reference['path']}")
        _assert_no_open_files(root, ignored_paths={lock_path})
        receipt_item["status"] = "deleting"
        _atomic_json(root, receipt_path, receipt)
        path.unlink()
        _fsync_directory(path.parent)
        receipt_item["status"] = "removed"
        receipt["observed"].append({"path": candidate["path"], "result": "removed"})
        _atomic_json(root, receipt_path, receipt)
    receipt["status"] = "complete"
    _atomic_json(root, receipt_path, receipt)
    print(
        json.dumps(
            {
                "receipt": receipt_relative.as_posix(),
                "status": "complete",
                "removed": len(receipt["candidates"]),
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser(
        "plan", help="write a dry-run plan; never remove data"
    )
    plan_parser.add_argument("--repo-root", type=Path, required=True)
    plan_parser.add_argument("--manifest", type=Path, required=True)
    plan_parser.add_argument("--cleanup-root", required=True)
    plan_parser.add_argument(
        "--output", help="optional plan path relative to selected root"
    )
    apply_parser = subparsers.add_parser(
        "apply", help="apply an explicitly authorized plan"
    )
    apply_parser.add_argument("--repo-root", type=Path, required=True)
    apply_parser.add_argument(
        "--plan", required=True, help="plan path relative to repository root"
    )
    args = parser.parse_args()
    try:
        if args.command == "plan":
            _plan(args)
        else:
            _apply(args)
    except (CleanupError, OSError) as error:
        parser.exit(2, f"cleanup_0115: {error}\n")


if __name__ == "__main__":
    main()
