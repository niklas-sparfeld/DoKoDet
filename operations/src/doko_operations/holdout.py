"""Versioned, reviewed registry for shared system holdout groups."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SYSTEM_HOLDOUT_REGISTRY_SCHEMA_VERSION = "system-holdout-registry/v1"
SYSTEM_HOLDOUT_REGISTRY_ID = "system-holdout"
SYSTEM_HOLDOUT_GROUP_NAMES = frozenset({"session_id", "game_id", "table_setup", "source_lineage"})


class SystemHoldoutError(ValueError):
    """Raised when a system holdout registry or seal operation is invalid."""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise SystemHoldoutError("System holdout values must be finite JSON values.") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemHoldoutError(f"{field} must be a non-empty string.")
    return value


def _safe_identifier(value: Any, field: str) -> str:
    result = _required_string(value, field)
    if any(character in result for character in ("/", "\\", "\x00")):
        raise SystemHoldoutError(f"{field} must be a safe identifier.")
    return result


def _digest_field(value: Any, field: str) -> str:
    result = _required_string(value, field)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise SystemHoldoutError(f"{field} must be a lower-case SHA-256 digest.")
    return result


def _seal_core(seal: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: seal[key]
        for key in (
            "seal_id",
            "group_key",
            "review_state",
            "reviewer",
            "review_id",
            "reason",
            "sealed_at_utc",
        )
    }


def _registry_core(registry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": registry["schema_version"],
        "registry_id": registry["registry_id"],
        "registry_version": registry["registry_version"],
        "seals": [_seal_core(seal) for seal in registry["seals"]],
    }


def _validate_group_key(value: Any, context: str) -> tuple[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"name", "value"}:
        raise SystemHoldoutError(f"{context} must contain only name and value.")
    name = value.get("name")
    group_value = value.get("value")
    if name not in SYSTEM_HOLDOUT_GROUP_NAMES:
        raise SystemHoldoutError(f"{context}.name is not a supported group key.")
    return str(name), _safe_identifier(group_value, f"{context}.value")


def _validate_seal(value: Any, context: str) -> None:
    if not isinstance(value, Mapping):
        raise SystemHoldoutError(f"{context} must be an object.")
    expected = {
        "seal_id",
        "group_key",
        "review_state",
        "reviewer",
        "review_id",
        "reason",
        "sealed_at_utc",
    }
    if set(value) != expected:
        raise SystemHoldoutError(f"{context} has invalid fields.")
    _safe_identifier(value.get("seal_id"), f"{context}.seal_id")
    _validate_group_key(value.get("group_key"), f"{context}.group_key")
    if value.get("review_state") != "reviewed":
        raise SystemHoldoutError(f"{context}.review_state must be reviewed.")
    _safe_identifier(value.get("reviewer"), f"{context}.reviewer")
    _safe_identifier(value.get("review_id"), f"{context}.review_id")
    _required_string(value.get("reason"), f"{context}.reason")
    timestamp = _required_string(value.get("sealed_at_utc"), f"{context}.sealed_at_utc")
    if not timestamp.endswith("Z"):
        raise SystemHoldoutError(f"{context}.sealed_at_utc must use UTC with a Z suffix.")
    try:
        datetime.fromisoformat(timestamp[:-1] + "+00:00")
    except ValueError as exc:
        raise SystemHoldoutError(f"{context}.sealed_at_utc must be ISO-8601.") from exc


def validate_system_holdout_registry(payload: Mapping[str, Any]) -> None:
    """Validate the strict shared registry contract."""

    expected = {
        "schema_version",
        "registry_id",
        "registry_version",
        "seals",
        "registry_digest",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise SystemHoldoutError("System holdout registry has invalid fields.")
    if payload.get("schema_version") != SYSTEM_HOLDOUT_REGISTRY_SCHEMA_VERSION:
        raise SystemHoldoutError("Unsupported system holdout registry schema_version.")
    if payload.get("registry_id") != SYSTEM_HOLDOUT_REGISTRY_ID:
        raise SystemHoldoutError("System holdout registry_id is invalid.")
    version = payload.get("registry_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise SystemHoldoutError("System holdout registry_version must be a non-negative integer.")
    seals = payload.get("seals")
    if not isinstance(seals, list) or len(seals) != version:
        raise SystemHoldoutError("System holdout seals must match registry_version.")
    seal_ids: set[str] = set()
    groups: set[tuple[str, str]] = set()
    for index, seal in enumerate(seals):
        _validate_seal(seal, f"system holdout seals[{index}]")
        seal_id = str(seal["seal_id"])
        if seal_id in seal_ids:
            raise SystemHoldoutError("System holdout seal IDs must be unique.")
        seal_ids.add(seal_id)
        group = _validate_group_key(seal["group_key"], f"system holdout seals[{index}].group_key")
        if group in groups:
            raise SystemHoldoutError("A system holdout group may be sealed only once.")
        groups.add(group)
    if payload.get("registry_digest") != _digest(_registry_core(payload)):
        raise SystemHoldoutError("System holdout registry_digest does not match its contents.")


def empty_system_holdout_registry() -> dict[str, Any]:
    """Return the in-memory empty registry without creating an artifact."""

    core = {
        "schema_version": SYSTEM_HOLDOUT_REGISTRY_SCHEMA_VERSION,
        "registry_id": SYSTEM_HOLDOUT_REGISTRY_ID,
        "registry_version": 0,
        "seals": [],
    }
    return {**core, "registry_digest": _digest(core)}


def load_system_holdout_registry(path: str | Path) -> dict[str, Any]:
    """Load a registry, or return an empty registry when no registry is present."""

    registry_path = Path(path)
    if not registry_path.exists():
        return empty_system_holdout_registry()
    try:
        value = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemHoldoutError(
            f"Could not read system holdout registry {registry_path}: {exc}"
        ) from exc
    if not isinstance(value, Mapping):
        raise SystemHoldoutError("System holdout registry must contain an object.")
    payload = dict(value)
    validate_system_holdout_registry(payload)
    return payload


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
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise SystemHoldoutError(f"Could not write system holdout registry {path}: {exc}") from exc


def seal_system_holdout_group(
    path: str | Path,
    *,
    group_name: str,
    group_value: str,
    reviewer: str,
    reason: str,
    review_id: str | None = None,
) -> dict[str, Any]:
    """Append one explicit reviewed seal and write a new registry version."""

    _validate_group_key({"name": group_name, "value": group_value}, "group_key")
    reviewer = _safe_identifier(reviewer, "reviewer")
    reason = _required_string(reason, "reason")
    registry_path = Path(path)
    current = load_system_holdout_registry(registry_path)
    group = {"name": group_name, "value": group_value}
    if any(seal["group_key"] == group for seal in current["seals"]):
        raise SystemHoldoutError(
            f"System holdout group is already sealed: {group_name}:{group_value}"
        )
    resolved_review_id = (
        review_id
        or "review-" + _digest({"group_key": group, "reviewer": reviewer, "reason": reason})[:24]
    )
    _safe_identifier(resolved_review_id, "review_id")
    seal = {
        "seal_id": "seal-"
        + _digest({"registry_version": current["registry_version"] + 1, "group_key": group})[:24],
        "group_key": group,
        "review_state": "reviewed",
        "reviewer": reviewer,
        "review_id": resolved_review_id,
        "reason": reason,
        "sealed_at_utc": _now(),
    }
    payload = {
        "schema_version": SYSTEM_HOLDOUT_REGISTRY_SCHEMA_VERSION,
        "registry_id": SYSTEM_HOLDOUT_REGISTRY_ID,
        "registry_version": current["registry_version"] + 1,
        "seals": [*current["seals"], seal],
    }
    payload["registry_digest"] = _digest(payload)
    validate_system_holdout_registry(payload)
    _atomic_write_json(registry_path, payload)
    return payload


def sealed_group_keys(registry: Mapping[str, Any]) -> frozenset[tuple[str, str]]:
    """Return the group keys sealed in a validated registry."""

    validate_system_holdout_registry(registry)
    return frozenset(
        (seal["group_key"]["name"], seal["group_key"]["value"]) for seal in registry["seals"]
    )


def validate_split_against_system_holdout(
    dataset: Mapping[str, Any], split: Mapping[str, Any], registry: Mapping[str, Any], task: str
) -> None:
    """Validate group isolation and the shared holdout rule for one component split."""

    held_out = sealed_group_keys(registry)
    entries = dataset.get("entries")
    if not isinstance(entries, list):
        raise SystemHoldoutError(f"{task} dataset must contain entries for split validation.")
    if "dataset_version_id" in dataset and split.get("dataset_version_id") != dataset.get(
        "dataset_version_id"
    ):
        raise SystemHoldoutError(f"{task} split references a different dataset version ID.")
    if "dataset_version_digest" in dataset and split.get("dataset_version_digest") != dataset.get(
        "dataset_version_digest"
    ):
        raise SystemHoldoutError(f"{task} split references a different dataset digest.")
    if "group_key_names" in dataset and split.get("group_key_names") != dataset.get(
        "group_key_names"
    ):
        raise SystemHoldoutError(f"{task} split group keys do not match the dataset version.")
    entry_groups: dict[str, frozenset[tuple[str, str]]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise SystemHoldoutError(f"{task} dataset entries[{index}] must be an object.")
        item_id = entry.get("dataset_item_id")
        if not isinstance(item_id, str) or not item_id:
            raise SystemHoldoutError(f"{task} dataset entries[{index}] has no item ID.")
        raw_groups = entry.get("group_keys")
        if not isinstance(raw_groups, list):
            raise SystemHoldoutError(f"{task} dataset entry {item_id} has no group keys.")
        groups: set[tuple[str, str]] = set()
        for group_index, raw_group in enumerate(raw_groups):
            if not isinstance(raw_group, list) or len(raw_group) != 2:
                raise SystemHoldoutError(
                    f"{task} dataset entry {item_id} group_keys[{group_index}] is invalid."
                )
            name, value = raw_group
            if not isinstance(name, str) or not isinstance(value, str) or not name or not value:
                raise SystemHoldoutError(
                    f"{task} dataset entry {item_id} group keys must be strings."
                )
            groups.add((name, value))
        if item_id in entry_groups:
            raise SystemHoldoutError(f"{task} dataset item IDs must be unique.")
        entry_groups[item_id] = frozenset(groups)

    partitions = {name: split.get(name) for name in ("train", "validation", "test", "unassigned")}
    if any(not isinstance(values, list) for values in partitions.values()):
        raise SystemHoldoutError(f"{task} split partitions must be lists.")
    item_partition: dict[str, str] = {}
    for partition, values in partitions.items():
        for item_id in values:
            if not isinstance(item_id, str) or not item_id:
                raise SystemHoldoutError(f"{task} split {partition} contains an invalid item ID.")
            if item_id in item_partition:
                raise SystemHoldoutError(f"{task} split item IDs must be unique across partitions.")
            if item_id not in entry_groups:
                raise SystemHoldoutError(f"{task} split names unknown item {item_id}.")
            item_partition[item_id] = partition
    missing = set(entry_groups) - set(item_partition)
    if missing:
        raise SystemHoldoutError(
            f"{task} split does not assign every dataset item: {', '.join(sorted(missing))}."
        )
    split_digest = split.get("split_version_digest")
    if isinstance(split_digest, str):
        split_digest_core = {
            key: value
            for key, value in split.items()
            if key not in {"split_version_id", "split_version_digest"}
        }
        if split_digest != _digest(split_digest_core):
            raise SystemHoldoutError(f"{task} split_version_digest does not match its contents.")

    group_partition: dict[tuple[str, str], str] = {}
    for item_id, groups in entry_groups.items():
        partition = item_partition[item_id]
        for group in groups:
            previous = group_partition.get(group)
            if previous is not None and previous != partition:
                raise SystemHoldoutError(
                    f"{task} split crosses group {group[0]}:{group[1]} between partitions."
                )
            group_partition[group] = partition
            if group in held_out and partition in {"train", "validation"}:
                raise SystemHoldoutError(
                    f"{task} split places system holdout group {group[0]}:{group[1]} "
                    f"in {partition}."
                )


def freeze_task_publication(
    task: str, staging_dir: str | Path, registry: Mapping[str, Any]
) -> tuple[Path, ...]:
    """Freeze component dataset and split manifests in a task staging directory.

    The operation is a publication step.  It leaves annotations, reviews, and source artifacts
    unchanged, and returns the additional frozen manifest paths.  Generic adapters without these
    component manifests are left unchanged.
    """

    root = Path(staging_dir)
    locations = {
        "cardevent_event_detection": (
            root / "cardevent" / "dataset" / "cardevent-dataset-version.json",
            root / "cardevent" / "split-proposal" / "cardevent-split-proposal.json",
            root / "cardevent" / "dataset" / "frozen-dataset-version.json",
            root / "cardevent" / "split" / "frozen-split-version.json",
            root / "cardevent" / "publication.json",
        ),
        "table_evidence_analysis": (
            root / "table-evidence" / "dataset" / "table-evidence-dataset-version.json",
            root / "table-evidence" / "split-proposal" / "table-evidence-split-proposal.json",
            root / "table-evidence" / "dataset" / "frozen-dataset-version.json",
            root / "table-evidence" / "split" / "frozen-split-version.json",
            root / "table-evidence" / "publication.json",
        ),
    }
    if task not in locations:
        raise SystemHoldoutError(f"Unknown task for publication: {task}")
    dataset_path, split_path, frozen_dataset_path, frozen_split_path, publication_path = locations[
        task
    ]
    if not dataset_path.exists() and not split_path.exists():
        return ()
    if not dataset_path.is_file() or not split_path.is_file():
        raise SystemHoldoutError(f"{task} publication needs both dataset and split manifests.")
    try:
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        split = json.loads(split_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemHoldoutError(f"Could not read {task} publication manifests: {exc}") from exc
    if not isinstance(dataset, Mapping) or not isinstance(split, Mapping):
        raise SystemHoldoutError(f"{task} publication manifests must contain objects.")
    validate_split_against_system_holdout(dataset, split, registry, task)
    frozen_dataset = {**dict(dataset), "dirty_state": False}
    dataset_digest_core = {
        key: value
        for key, value in frozen_dataset.items()
        if key not in {"dataset_version_id", "dataset_version_digest", "created_at"}
    }
    if task == "table_evidence_analysis":
        dataset_digest_core["entries"] = [
            {
                **entry,
                "group_keys": sorted(entry["group_keys"]),
                "eligibility": {
                    **entry["eligibility"],
                    "allowed_uses": sorted(entry["eligibility"]["allowed_uses"]),
                },
            }
            for entry in sorted(
                dataset_digest_core["entries"], key=lambda value: value["dataset_item_id"]
            )
        ]
        dataset_digest_core["allowed_use_filter"] = sorted(
            dataset_digest_core["allowed_use_filter"]
        )
        dataset_digest_core["group_key_names"] = sorted(dataset_digest_core["group_key_names"])
    frozen_dataset["dataset_version_digest"] = _digest(dataset_digest_core)
    frozen_split = {
        **dict(split),
        "dataset_version_digest": frozen_dataset["dataset_version_digest"],
    }
    split_digest_core = {
        key: value
        for key, value in frozen_split.items()
        if key not in {"split_version_id", "split_version_digest"}
    }
    frozen_split["split_version_digest"] = _digest(split_digest_core)
    publication = {
        "schema_version": "data-publication/v1",
        "task": task,
        "state": "frozen",
        "dataset_version_id": frozen_dataset["dataset_version_id"],
        "dataset_version_digest": frozen_dataset["dataset_version_digest"],
        "split_version_id": frozen_split["split_version_id"],
        "split_version_digest": frozen_split["split_version_digest"],
        "system_holdout_registry_id": registry["registry_id"],
        "system_holdout_registry_version": registry["registry_version"],
        "system_holdout_registry_digest": registry["registry_digest"],
        "published_at_utc": _now(),
    }
    publication["publication_digest"] = _digest(
        {key: value for key, value in publication.items() if key != "publication_digest"}
    )
    _atomic_write_json(dataset_path, frozen_dataset)
    _atomic_write_json(split_path, frozen_split)
    _atomic_write_json(frozen_dataset_path, frozen_dataset)
    _atomic_write_json(frozen_split_path, frozen_split)
    _atomic_write_json(publication_path, publication)
    return dataset_path, split_path, frozen_dataset_path, frozen_split_path, publication_path


__all__ = [
    "SYSTEM_HOLDOUT_GROUP_NAMES",
    "SYSTEM_HOLDOUT_REGISTRY_ID",
    "SYSTEM_HOLDOUT_REGISTRY_SCHEMA_VERSION",
    "SystemHoldoutError",
    "empty_system_holdout_registry",
    "freeze_task_publication",
    "load_system_holdout_registry",
    "seal_system_holdout_group",
    "sealed_group_keys",
    "validate_split_against_system_holdout",
    "validate_system_holdout_registry",
]
