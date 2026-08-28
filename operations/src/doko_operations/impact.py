"""Cross-task source permission and retirement impact analysis.

Source bundles and derived data are immutable.  A permission withdrawal or retirement therefore
writes a versioned source-state document and a stale-artifact receipt.  Status and validation read
those documents; they never rewrite the source bundle or the historical derived artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .intake import TASKS, discover_bundle_paths

SOURCE_STATE_SCHEMA_VERSION = "source-record-state/v1"
SOURCE_IMPACT_REPORT_SCHEMA_VERSION = "source-impact-report/v1"
STALE_ARTIFACT_RECEIPT_SCHEMA_VERSION = "stale-artifact-receipt/v1"
RETIREMENT_STATES = frozenset({"deletion_requested", "retired"})
RETENTION_STATES = frozenset({"active", "deletion_requested", "deleted", "retired"})
ARTIFACT_KINDS = (
    "annotations",
    "datasets",
    "splits",
    "caches",
    "runs",
    "model_bundles",
)
_CONTROL_DIRECTORIES = frozenset(
    {
        "source-record-states",
        "source-impact-reports",
        "stale-artifact-receipts",
        "system-holdout-registry",
    }
)
_TASK_ALIASES = {
    "cardevent_event_detection": "cardevent_event_detection",
    "table_evidence_analysis": "table_evidence_analysis",
    "table_evidence_analyzer_identity_crop": "table_evidence_analysis",
}
_IDENTIFIER_KEYS = (
    "annotation_set_id",
    "dataset_version_id",
    "split_version_id",
    "cache_id",
    "derived_artifact_id",
    "run_id",
    "training_run_id",
    "model_bundle_id",
    "proposal_generator_run_id",
    "receipt_id",
)
_REFERENCE_KEYS = {
    "annotation": "annotation",
    "annotations": "annotation",
    "annotation_set_id": "annotation",
    "dataset_version_id": "dataset",
    "dataset_version_digest": "dataset_digest",
    "split_version_id": "split",
    "split_version_digest": "split_digest",
    "cache_id": "cache",
    "derived_artifact_id": "cache",
    "run_id": "run",
    "training_run_id": "run",
    "model_bundle_id": "model_bundle",
    "proposal_generator_run_id": "proposal",
}


class SourceImpactError(ValueError):
    """Raised when source state or impact data is invalid."""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise SourceImpactError("Impact values must be finite JSON values.") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceImpactError(f"{field} must be a non-empty string.")
    return value


def _safe_identifier(value: Any, field: str) -> str:
    result = _required_string(value, field)
    if any(character in result for character in ("/", "\\", "\x00")):
        raise SourceImpactError(f"{field} must be a safe identifier.")
    return result


def _digest_value(value: Any, field: str) -> str:
    result = _required_string(value, field)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise SourceImpactError(f"{field} must be a lower-case SHA-256 digest.")
    return result


def _resolve_path(repository_root: str | Path, value: str | Path | None, default: str) -> Path:
    repository = Path(repository_root).expanduser().resolve()
    path = repository / default if value is None else Path(value).expanduser()
    if not path.is_absolute():
        path = repository / path
    return path.resolve()


def _default_bundle_root(repository_root: Path) -> Path:
    canonical = repository_root / "data" / "intake" / "recordings"
    if canonical.exists():
        return canonical
    fixture = repository_root / "fixtures" / "repository-bundle" / "v1"
    return fixture if fixture.exists() else canonical


def _read_object(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceImpactError(f"Could not read {context} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SourceImpactError(f"{context} must contain an object: {path}")
    return value


def _source_bundle(
    repository_root: Path, source_asset_id: str, bundle_root: str | Path | None
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    root = _resolve_path(repository_root, bundle_root, "data/intake/recordings")
    if bundle_root is None and not root.exists():
        root = _default_bundle_root(repository_root)
    for bundle in discover_bundle_paths(root):
        source_path = bundle / "source-record.json"
        if not source_path.is_file():
            continue
        source = _read_object(source_path, "source record")
        if source.get("source_asset_id") != source_asset_id:
            continue
        enrollment = _read_object(bundle / "initial-task-enrollment.json", "task enrollment")
        return bundle, source, enrollment
    raise SourceImpactError(f"Source asset was not found in repository intake: {source_asset_id}")


def _state_core(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: state[key]
        for key in (
            "schema_version",
            "source_asset_id",
            "source_sha256",
            "version",
            "retention_state",
            "source_permission",
            "allowed_uses",
            "operator",
            "reason",
            "created_at_utc",
            "previous_state_version",
        )
    }


def validate_source_state(payload: Mapping[str, Any]) -> None:
    """Validate one versioned source-state document."""

    expected = {
        "schema_version",
        "source_asset_id",
        "source_sha256",
        "version",
        "retention_state",
        "source_permission",
        "allowed_uses",
        "operator",
        "reason",
        "created_at_utc",
        "previous_state_version",
        "state_digest",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise SourceImpactError("Source state has invalid fields.")
    if payload.get("schema_version") != SOURCE_STATE_SCHEMA_VERSION:
        raise SourceImpactError("Unsupported source state schema_version.")
    _safe_identifier(payload.get("source_asset_id"), "source state source_asset_id")
    _digest_value(payload.get("source_sha256"), "source state source_sha256")
    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise SourceImpactError("Source state version must be a positive integer.")
    if payload.get("retention_state") not in RETIREMENT_STATES:
        raise SourceImpactError("Source state retention_state must request deletion or retirement.")
    _required_string(payload.get("source_permission"), "source state source_permission")
    allowed_uses = payload.get("allowed_uses")
    if not isinstance(allowed_uses, list) or any(
        not isinstance(value, str) for value in allowed_uses
    ):
        raise SourceImpactError("Source state allowed_uses must be a list of strings.")
    _safe_identifier(payload.get("operator"), "source state operator")
    _required_string(payload.get("reason"), "source state reason")
    timestamp = _required_string(payload.get("created_at_utc"), "source state created_at_utc")
    if not timestamp.endswith("Z"):
        raise SourceImpactError("Source state created_at_utc must use UTC.")
    previous = payload.get("previous_state_version")
    if isinstance(previous, bool) or not isinstance(previous, int) or previous < 0:
        raise SourceImpactError("Source state previous_state_version is invalid.")
    if previous != version - 1:
        raise SourceImpactError("Source state versions must be consecutive.")
    if payload.get("state_digest") != _digest(_state_core(payload)):
        raise SourceImpactError("Source state digest does not match its contents.")


def _source_state_paths(artifacts_root: Path, source_asset_id: str) -> tuple[Path, ...]:
    state_root = artifacts_root / "source-record-states"
    if not state_root.is_dir():
        return ()
    return tuple(
        sorted(
            (path for path in state_root.glob(f"{source_asset_id}-v*.json") if path.is_file()),
            key=lambda path: path.as_posix(),
        )
    )


def load_current_source_state(
    artifacts_root: str | Path,
    source_asset_id: str,
    *,
    source_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load the latest retirement state, falling back to the immutable source record."""

    _safe_identifier(source_asset_id, "source_asset_id")
    root = Path(artifacts_root).expanduser().resolve()
    states: list[dict[str, Any]] = []
    for path in _source_state_paths(root, source_asset_id):
        value = _read_object(path, "source state")
        validate_source_state(value)
        if value["source_asset_id"] != source_asset_id:
            raise SourceImpactError(f"Source state identity differs: {path}")
        states.append(value)
    if states:
        states.sort(key=lambda value: value["version"])
        versions = [value["version"] for value in states]
        if versions != list(range(1, len(versions) + 1)):
            raise SourceImpactError("Source state versions are not a complete sequence.")
        return states[-1]
    if source_record is None:
        return {
            "source_asset_id": source_asset_id,
            "retention_state": "active",
            "source_permission": "unknown",
            "allowed_uses": [],
            "version": 0,
        }
    digest = source_record.get("sha256")
    if not isinstance(digest, str):
        raise SourceImpactError(f"Source record has no digest: {source_asset_id}")
    return {
        "source_asset_id": source_asset_id,
        "source_sha256": digest,
        "retention_state": source_record.get("retention_state", "active"),
        "source_permission": source_record.get("source_permission"),
        "allowed_uses": list(source_record.get("allowed_uses", [])),
        "version": 0,
    }


def _walk(value: Any):
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _source_references(payload: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    source_ids: set[str] = set()
    digests: set[str] = set()
    for value in _walk(payload):
        source_id = value.get("source_asset_id")
        if isinstance(source_id, str):
            source_ids.add(source_id)
        if isinstance(value.get("source_sha256"), str):
            digests.add(value["source_sha256"])
        if isinstance(value.get("source_digest"), str):
            digests.add(value["source_digest"])
        if value.get("kind") == "source_asset" and isinstance(value.get("id"), str):
            source_ids.add(value["id"])
            if isinstance(value.get("digest"), str):
                digests.add(value["digest"])
    return source_ids, digests


def _references(payload: Mapping[str, Any]) -> dict[str, set[str]]:
    result = {name: set() for name in set(_REFERENCE_KEYS.values())}
    for value in _walk(payload):
        for field, kind in _REFERENCE_KEYS.items():
            candidate = value.get(field)
            if isinstance(candidate, str):
                result[kind].add(candidate)
    return result


def _identifiers(payload: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for value in _walk(payload):
        for key in _IDENTIFIER_KEYS:
            candidate = value.get(key)
            if isinstance(candidate, str):
                result.add(candidate)
    return result


def _task(payload: Mapping[str, Any], path: Path) -> str | None:
    for value in _walk(payload):
        candidate = value.get("task") or value.get("data_task")
        if isinstance(candidate, str):
            return _TASK_ALIASES.get(candidate, candidate)
    for part in path.parts:
        if part in _TASK_ALIASES:
            return _TASK_ALIASES[part]
    return None


def _classify(payload: Mapping[str, Any], path: Path) -> tuple[str, ...]:
    schema = str(payload.get("schema_version", "")).lower()
    lowered = "/".join(path.parts).lower()
    categories: set[str] = set()
    if (
        "annotation" in schema
        or "annotation" in lowered
        or isinstance(payload.get("annotation_set_id"), str)
    ):
        categories.add("annotations")
    if "dataset-version" in schema or "/dataset/" in f"/{lowered}/":
        categories.add("datasets")
    if "split" in schema or "/split/" in f"/{lowered}/":
        categories.add("splits")
    if "cache" in schema or "cache" in lowered or "cache_id" in _identifiers(payload):
        categories.add("caches")
    if (
        "training-run" in schema
        or "review-run" in schema
        or isinstance(payload.get("run_id"), str)
        or "/runs/" in f"/{lowered}/"
        or "/review-runs/" in f"/{lowered}/"
    ):
        categories.add("runs")
    if (
        "model_bundle_id" in _identifiers(payload)
        or "model-bundle" in schema
        or "/models/" in f"/{lowered}/"
    ):
        categories.add("model_bundles")
    return tuple(sorted(categories, key=ARTIFACT_KINDS.index))


def _artifact_id(payload: Mapping[str, Any], path: Path, kind: str) -> str:
    preferred = {
        "annotations": ("annotation_set_id", "annotation_id"),
        "datasets": ("dataset_version_id",),
        "splits": ("split_version_id",),
        "caches": ("cache_id", "derived_artifact_id"),
        "runs": ("training_run_id", "run_id"),
        "model_bundles": ("model_bundle_id",),
    }[kind]
    for value in _walk(payload):
        for key in preferred:
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
    return path.stem


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _path_references(payload: Mapping[str, Any], path: Path, artifact_root: Path) -> set[Path]:
    result: set[Path] = set()
    fields = {"annotation", "annotations", "review", "reviews", "cache", "run", "model"}
    for value in _walk(payload):
        for field, candidate in value.items():
            if field not in fields:
                continue
            candidates = candidate if isinstance(candidate, list) else [candidate]
            for item in candidates:
                if not isinstance(item, str) or not item or item.startswith("http"):
                    continue
                for base in (path.parent, *path.parents):
                    resolved = (base / item).resolve()
                    try:
                        resolved.relative_to(artifact_root.resolve())
                    except ValueError:
                        continue
                    if resolved.is_file():
                        result.add(resolved)
                        break
    return result


def _artifact_records(artifact_root: Path, repository_root: Path) -> list[dict[str, Any]]:
    if not artifact_root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(artifact_root.rglob("*.json"), key=lambda item: item.as_posix()):
        try:
            relative = path.relative_to(artifact_root)
        except ValueError:
            continue
        if _CONTROL_DIRECTORIES.intersection(relative.parts):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        categories = _classify(payload, path)
        if not categories:
            continue
        source_ids, source_digests = _source_references(payload)
        records.append(
            {
                "path": _relative_path(path, repository_root),
                "absolute_path": path,
                "payload": payload,
                "categories": categories,
                "task": _task(payload, path),
                "source_ids": source_ids,
                "source_digests": source_digests,
                "references": _references(payload),
                "identifiers": _identifiers(payload),
                "path_references": _path_references(payload, path, artifact_root),
            }
        )
    return records


def _link_artifacts(records: list[dict[str, Any]]) -> None:
    """Propagate source links through dataset, split, run, and model references."""

    path_sources: dict[Path, set[str]] = {}
    identifier_sources: dict[tuple[str, str], set[str]] = {}
    for record in records:
        for target in record["path_references"]:
            path_sources.setdefault(target, set()).update(record["source_ids"])
        for kind, values in record["references"].items():
            for value in values:
                identifier_sources.setdefault((kind, value), set()).update(record["source_ids"])
        for digest in record["source_digests"]:
            identifier_sources.setdefault(("source_digest", digest), set()).update(
                record["source_ids"]
            )
    changed = True
    while changed:
        changed = False
        for record in records:
            linked = set(record["source_ids"])
            linked.update(path_sources.get(record["absolute_path"], set()))
            for kind, values in record["references"].items():
                for value in values:
                    linked.update(identifier_sources.get((kind, value), set()))
            if linked != record["source_ids"]:
                record["source_ids"] = linked
                changed = True
                for kind, values in record["references"].items():
                    for value in values:
                        identifier_sources.setdefault((kind, value), set()).update(linked)
                for target in record["path_references"]:
                    path_sources.setdefault(target, set()).update(linked)


def _public_artifact(record: Mapping[str, Any], kind: str, repository_root: Path) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": _artifact_id(record["payload"], record["absolute_path"], kind),
        "path": record["path"],
        "task": record["task"],
    }


def _task_enrollments(enrollment: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    values = enrollment.get("enrollments")
    if not isinstance(values, list):
        return {}
    return {
        item["task"]: item
        for item in values
        if isinstance(item, Mapping) and isinstance(item.get("task"), str)
    }


def analyze_source_impact(
    repository_root: str | Path,
    source_asset_id: str,
    *,
    bundle_root: str | Path | None = None,
    artifacts_root: str | Path | None = None,
    requested_retention_state: str | None = None,
) -> dict[str, Any]:
    """Return a deterministic cross-task impact report for one source asset."""

    repository = Path(repository_root).expanduser().resolve()
    _safe_identifier(source_asset_id, "source_asset_id")
    bundle, source, enrollment = _source_bundle(repository, source_asset_id, bundle_root)
    artifact_root = _resolve_path(repository, artifacts_root, "data/operations")
    state = load_current_source_state(artifact_root, source_asset_id, source_record=source)
    if requested_retention_state is not None:
        if requested_retention_state not in RETENTION_STATES:
            raise SourceImpactError("requested_retention_state is invalid.")
        state = {**state, "retention_state": requested_retention_state}
    records = _artifact_records(artifact_root, repository)
    _link_artifacts(records)
    source_digest = str(source.get("sha256", ""))
    affected: list[dict[str, Any]] = []
    for record in records:
        if (
            source_asset_id not in record["source_ids"]
            and source_digest not in record["source_digests"]
        ):
            continue
        for kind in record["categories"]:
            affected.append(_public_artifact(record, kind, repository))
    affected.sort(key=lambda item: (item["kind"], item["path"], item["id"]))
    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in affected:
        key = (item["kind"], item["path"])
        if key not in seen:
            seen.add(key)
            deduplicated.append(item)
    enrollments = _task_enrollments(enrollment)
    task_impacts: list[dict[str, Any]] = []
    for task in TASKS:
        task_artifacts = [item for item in deduplicated if item["task"] in {None, task}]
        task_enrollment = enrollments.get(task)
        task_impacts.append(
            {
                "task": task,
                "task_enrollment_id": (
                    task_enrollment.get("task_enrollment_id") if task_enrollment else None
                ),
                "disposition": task_enrollment.get("disposition") if task_enrollment else None,
                "lifecycle_state": (
                    task_enrollment.get("lifecycle_state") if task_enrollment else None
                ),
                "impact_state": (
                    "stale"
                    if state["retention_state"] != "active" and task_artifacts
                    else ("blocked" if state["retention_state"] != "active" else "none")
                ),
                "affected_artifacts": task_artifacts,
            }
        )
    counts = {kind: sum(item["kind"] == kind for item in deduplicated) for kind in ARTIFACT_KINDS}
    report_core = {
        "schema_version": SOURCE_IMPACT_REPORT_SCHEMA_VERSION,
        "source_asset_id": source_asset_id,
        "source_sha256": source_digest,
        "source_bundle": _relative_path(bundle, repository),
        "source_state_version": state.get("version", 0),
        "retention_state": state.get("retention_state"),
        "source_permission": state.get("source_permission"),
        "allowed_uses": sorted(state.get("allowed_uses", [])),
        "task_impacts": task_impacts,
        "affected_tasks": [item["task"] for item in task_impacts if item["impact_state"] != "none"],
        "affected_artifacts": deduplicated,
        "artifact_counts": counts,
    }
    return {**report_core, "impact_digest": _digest(report_core)}


def analyze_repository_impacts(
    repository_root: str | Path,
    *,
    bundle_root: str | Path | None = None,
    artifacts_root: str | Path | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return deterministic impact reports for every readable intake source."""

    repository = Path(repository_root).expanduser().resolve()
    root = _resolve_path(repository, bundle_root, "data/intake/recordings")
    if bundle_root is None and not root.exists():
        root = _default_bundle_root(repository)
    source_ids: set[str] = set()
    for bundle in discover_bundle_paths(root):
        try:
            source = _read_object(bundle / "source-record.json", "source record")
        except SourceImpactError:
            continue
        source_id = source.get("source_asset_id")
        if isinstance(source_id, str):
            source_ids.add(source_id)
    return tuple(
        analyze_source_impact(
            repository,
            source_id,
            bundle_root=root,
            artifacts_root=artifacts_root,
        )
        for source_id in sorted(source_ids)
    )


def validate_source_impact_report(payload: Mapping[str, Any]) -> None:
    """Validate the deterministic source-impact report contract."""

    expected = {
        "schema_version",
        "source_asset_id",
        "source_sha256",
        "source_bundle",
        "source_state_version",
        "retention_state",
        "source_permission",
        "allowed_uses",
        "task_impacts",
        "affected_tasks",
        "affected_artifacts",
        "artifact_counts",
        "impact_digest",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise SourceImpactError("Source impact report has invalid fields.")
    if payload.get("schema_version") != SOURCE_IMPACT_REPORT_SCHEMA_VERSION:
        raise SourceImpactError("Unsupported source impact report schema_version.")
    _safe_identifier(payload.get("source_asset_id"), "impact source_asset_id")
    _digest_value(payload.get("source_sha256"), "impact source_sha256")
    if payload.get("retention_state") not in RETENTION_STATES:
        raise SourceImpactError("Impact retention_state is invalid.")
    if not isinstance(payload.get("task_impacts"), list) or not isinstance(
        payload.get("affected_artifacts"), list
    ):
        raise SourceImpactError("Impact task_impacts and affected_artifacts must be lists.")
    if payload.get("impact_digest") != _digest(
        {key: payload[key] for key in expected if key != "impact_digest"}
    ):
        raise SourceImpactError("Impact report digest does not match its contents.")


def validate_stale_artifact_receipt(payload: Mapping[str, Any]) -> None:
    """Validate one immutable stale-artifact receipt."""

    expected = {
        "schema_version",
        "receipt_id",
        "source_asset_id",
        "source_sha256",
        "source_state_version",
        "retention_state",
        "operator",
        "reason",
        "created_at_utc",
        "impact_report_digest",
        "affected_tasks",
        "affected_artifacts",
        "receipt_digest",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise SourceImpactError("Stale-artifact receipt has invalid fields.")
    if payload.get("schema_version") != STALE_ARTIFACT_RECEIPT_SCHEMA_VERSION:
        raise SourceImpactError("Unsupported stale-artifact receipt schema_version.")
    _safe_identifier(payload.get("receipt_id"), "stale receipt receipt_id")
    _safe_identifier(payload.get("source_asset_id"), "stale receipt source_asset_id")
    _digest_value(payload.get("source_sha256"), "stale receipt source_sha256")
    if payload.get("retention_state") not in RETIREMENT_STATES:
        raise SourceImpactError("Stale receipt retention_state is invalid.")
    _safe_identifier(payload.get("operator"), "stale receipt operator")
    _required_string(payload.get("reason"), "stale receipt reason")
    _required_string(payload.get("created_at_utc"), "stale receipt created_at_utc")
    if not isinstance(payload.get("affected_tasks"), list) or not isinstance(
        payload.get("affected_artifacts"), list
    ):
        raise SourceImpactError("Stale receipt affected values must be lists.")
    if payload.get("receipt_digest") != _digest(
        {key: payload[key] for key in expected if key != "receipt_digest"}
    ):
        raise SourceImpactError("Stale receipt digest does not match its contents.")


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(
                payload, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
            )
            handle.write("\n")
            temporary = Path(handle.name)
        if path.exists():
            existing = path.read_bytes()
            if existing != temporary.read_bytes():
                raise SourceImpactError(
                    f"Immutable artifact already exists with different content: {path}"
                )
            temporary.unlink(missing_ok=True)
            return
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if isinstance(exc, SourceImpactError):
            raise
        raise SourceImpactError(f"Could not write impact artifact {path}: {exc}") from exc


def _find_existing_receipt(artifacts_root: Path, receipt_id: str) -> dict[str, Any] | None:
    path = artifacts_root / "stale-artifact-receipts" / f"{receipt_id}.json"
    if not path.is_file():
        return None
    value = _read_object(path, "stale-artifact receipt")
    validate_stale_artifact_receipt(value)
    return value


def retire_source(
    repository_root: str | Path,
    source_asset_id: str,
    *,
    bundle_root: str | Path | None = None,
    artifacts_root: str | Path | None = None,
    retention_state: str,
    operator: str,
    reason: str,
) -> dict[str, Any]:
    """Record a permission withdrawal or retirement and its immutable stale impact receipt."""

    if retention_state not in RETIREMENT_STATES:
        raise SourceImpactError("retention_state must be deletion_requested or retired.")
    operator = _safe_identifier(operator, "operator")
    reason = _required_string(reason, "reason")
    repository = Path(repository_root).expanduser().resolve()
    _, source, _ = _source_bundle(repository, source_asset_id, bundle_root)
    artifact_root = _resolve_path(repository, artifacts_root, "data/operations")
    current = load_current_source_state(artifact_root, source_asset_id, source_record=source)
    if (
        current.get("version", 0) > 0
        and current.get("retention_state") == retention_state
        and current.get("operator") == operator
        and current.get("reason") == reason
    ):
        report = analyze_source_impact(
            repository, source_asset_id, bundle_root=bundle_root, artifacts_root=artifact_root
        )
        receipt_id = "stale-" + _digest({"source_asset_id": source_asset_id, "state": current})[:24]
        existing = _find_existing_receipt(artifact_root, receipt_id)
        if existing is not None and existing["impact_report_digest"] == report["impact_digest"]:
            return {"source_state": current, "impact_report": report, "stale_receipt": existing}
    version = int(current.get("version", 0)) + 1
    state = {
        "schema_version": SOURCE_STATE_SCHEMA_VERSION,
        "source_asset_id": source_asset_id,
        "source_sha256": source["sha256"],
        "version": version,
        "retention_state": retention_state,
        "source_permission": "withdrawn",
        "allowed_uses": [],
        "operator": operator,
        "reason": reason,
        "created_at_utc": _now(),
        "previous_state_version": version - 1,
    }
    state["state_digest"] = _digest(_state_core(state))
    validate_source_state(state)
    state_path = artifact_root / "source-record-states" / f"{source_asset_id}-v{version}.json"
    _atomic_write_json(state_path, state)
    report = analyze_source_impact(
        repository, source_asset_id, bundle_root=bundle_root, artifacts_root=artifact_root
    )
    validate_source_impact_report(report)
    report_path = (
        artifact_root
        / "source-impact-reports"
        / f"{source_asset_id}-{report['impact_digest'][:24]}.json"
    )
    _atomic_write_json(report_path, report)
    receipt_id = "stale-" + _digest({"source_asset_id": source_asset_id, "state": state})[:24]
    receipt = {
        "schema_version": STALE_ARTIFACT_RECEIPT_SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "source_asset_id": source_asset_id,
        "source_sha256": source["sha256"],
        "source_state_version": version,
        "retention_state": retention_state,
        "operator": operator,
        "reason": reason,
        "created_at_utc": state["created_at_utc"],
        "impact_report_digest": report["impact_digest"],
        "affected_tasks": report["affected_tasks"],
        "affected_artifacts": report["affected_artifacts"],
    }
    receipt["receipt_digest"] = _digest(
        {key: value for key, value in receipt.items() if key != "receipt_digest"}
    )
    validate_stale_artifact_receipt(receipt)
    receipt_path = artifact_root / "stale-artifact-receipts" / f"{receipt_id}.json"
    _atomic_write_json(receipt_path, receipt)
    return {"source_state": state, "impact_report": report, "stale_receipt": receipt}


def withdraw_source_permission(
    repository_root: str | Path,
    source_asset_id: str,
    *,
    operator: str,
    reason: str,
    bundle_root: str | Path | None = None,
    artifacts_root: str | Path | None = None,
) -> dict[str, Any]:
    """Record a permission withdrawal as a deletion-requested source state."""

    return retire_source(
        repository_root,
        source_asset_id,
        bundle_root=bundle_root,
        artifacts_root=artifacts_root,
        retention_state="deletion_requested",
        operator=operator,
        reason=reason,
    )


__all__ = [
    "ARTIFACT_KINDS",
    "RETIREMENT_STATES",
    "RETENTION_STATES",
    "SOURCE_IMPACT_REPORT_SCHEMA_VERSION",
    "SOURCE_STATE_SCHEMA_VERSION",
    "STALE_ARTIFACT_RECEIPT_SCHEMA_VERSION",
    "SourceImpactError",
    "analyze_repository_impacts",
    "analyze_source_impact",
    "load_current_source_state",
    "retire_source",
    "validate_source_impact_report",
    "validate_source_state",
    "validate_stale_artifact_receipt",
    "withdraw_source_permission",
]
