"""Group-safe CardEventNet development partition assignment.

The active split is a small operations artifact.  It contains recording identities and the
complete leakage-group facts needed to prove that one assignment does not split connected source
material.  Source bundles and review artifacts remain read-only.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .holdout import load_system_holdout_registry, sealed_group_keys

try:
    import fcntl
except ImportError:  # pragma: no cover - the supported local runtime is macOS/Linux.
    fcntl = None  # type: ignore[assignment]

CARD_EVENT_TASK = "cardevent_event_detection"
CARD_EVENT_DEVELOPMENT_SPLIT_SCHEMA_VERSION = "cardevent-development-split/v1"
CARD_EVENT_DEVELOPMENT_SPLIT_ACTIVE_SCHEMA_VERSION = "cardevent-development-split-active/v1"
CARD_EVENT_DEVELOPMENT_SPLIT_PREVIEW_SCHEMA_VERSION = "cardevent-development-split-preview/v1"
CARD_EVENT_DEVELOPMENT_SPLIT_APPLY_SCHEMA_VERSION = "cardevent-development-split-apply/v1"
CARD_EVENT_DEVELOPMENT_SPLIT_RECEIPT_TYPE = "development_split_assignment"
DEVELOPMENT_PARTITIONS = ("train", "validation", "unassigned")
ALL_PARTITIONS = (*DEVELOPMENT_PARTITIONS, "test")
GROUP_KEY_NAMES = ("game_id", "session_id", "source_lineage", "table_setup")
_DIGEST_LENGTH = 64


class CardEventDevelopmentSplitError(ValueError):
    """Base error for the development split operation."""


class CardEventDevelopmentSplitConflict(CardEventDevelopmentSplitError):
    """The operation was based on a stale active split or preview."""


class CardEventDevelopmentSplitValidationError(CardEventDevelopmentSplitError):
    """The requested assignment is not allowed."""


@dataclass(frozen=True, slots=True)
class CardEventDevelopmentRecording:
    """The read-only facts used to evaluate one recording assignment."""

    recording_id: str
    source_asset_id: str
    source_sha256: str
    source_permission: str
    allowed_uses: tuple[str, ...]
    retention_state: str
    task_selected: bool
    review_state: str
    group_keys: tuple[tuple[str, str], ...]
    review_event_count: int = 0


class CardEventDevelopmentSplitStore:
    """Persist immutable split versions and one atomic active pointer."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.artifact_root = self.workspace_root / "cardevent-development-split"
        self.active_path = self.artifact_root / "active.json"
        self.version_root = self.artifact_root / "versions"
        self.receipt_root = self.artifact_root / "receipts"
        self.lock_path = self.artifact_root / ".lock"

    def read(
        self,
        recordings: Sequence[CardEventDevelopmentRecording],
    ) -> dict[str, Any]:
        """Return the active split, including newly discovered recordings as unassigned."""

        normalized = _normalize_recordings(recordings)
        with _split_lock(self.lock_path, exclusive=False):
            return self._read_locked(normalized)

    def validate_published_artifacts(self) -> None:
        """Validate the active pointer and all immutable split artifacts."""

        if not self.artifact_root.is_dir():
            return
        version_paths = sorted(self.version_root.glob("*.json"))
        receipt_paths = sorted(self.receipt_root.glob("*.json"))
        if not self.active_path.is_file():
            if version_paths or receipt_paths:
                raise CardEventDevelopmentSplitError(
                    "Published development split artifacts have no active pointer."
                )
            return
        pointer = _read_json(self.active_path)
        if pointer.get("schema_version") != CARD_EVENT_DEVELOPMENT_SPLIT_ACTIVE_SCHEMA_VERSION:
            raise CardEventDevelopmentSplitError(
                "The active development split pointer is invalid."
            )
        version_id = pointer.get("split_version_id")
        version_digest = pointer.get("split_version_digest")
        if not isinstance(version_id, str) or not isinstance(version_digest, str):
            raise CardEventDevelopmentSplitError(
                "The active development split pointer is incomplete."
            )
        active_path = self.version_root / f"{version_id}.json"
        if not active_path.is_file():
            raise CardEventDevelopmentSplitError(
                "The active development split version is missing."
            )
        for path in version_paths:
            version = _read_json(path)
            _validate_split(version)
            if path == active_path and (
                version["split_version_id"] != version_id
                or version["split_version_digest"] != version_digest
            ):
                raise CardEventDevelopmentSplitError(
                    "The active development split pointer is stale."
                )
        for path in receipt_paths:
            _validate_receipt(_read_json(path))

    def preview(
        self,
        recordings: Sequence[CardEventDevelopmentRecording],
        *,
        recording_id: str,
        destination: str,
        expected_active_split_digest: str,
    ) -> dict[str, Any]:
        """Build a deterministic group-safe preview without writing an artifact."""

        _validate_destination(destination)
        _validate_digest(expected_active_split_digest, "expected_active_split_digest")
        normalized = _normalize_recordings(recordings)
        with _split_lock(self.lock_path, exclusive=False):
            split = self._read_locked(normalized)
            if split["split_version_digest"] != expected_active_split_digest:
                raise CardEventDevelopmentSplitConflict(
                    "The active development split changed. Refresh the recording and preview again."
                )
            return _build_preview(
                normalized,
                split,
                recording_id=recording_id,
                destination=destination,
                holdout_groups=self._holdout_groups(),
            )

    def apply(
        self,
        recordings: Sequence[CardEventDevelopmentRecording],
        *,
        recording_id: str,
        destination: str,
        expected_active_split_digest: str,
        preview_digest: str,
        operator: str,
    ) -> dict[str, Any]:
        """Validate a preview again and publish one new immutable split version."""

        _validate_destination(destination)
        _validate_digest(expected_active_split_digest, "expected_active_split_digest")
        _validate_digest(preview_digest, "preview_digest")
        operator = _validate_identifier(operator, "operator")
        normalized = _normalize_recordings(recordings)
        with _split_lock(self.lock_path, exclusive=True):
            current = self._read_locked(normalized)
            if current["split_version_digest"] != expected_active_split_digest:
                raise CardEventDevelopmentSplitConflict(
                    "The active development split changed. Refresh the recording and preview again."
                )
            preview = _build_preview(
                normalized,
                current,
                recording_id=recording_id,
                destination=destination,
                holdout_groups=self._holdout_groups(),
            )
            if preview["preview_digest"] != preview_digest:
                raise CardEventDevelopmentSplitConflict(
                    "The assignment preview is stale. Refresh the affected group and try again."
                )
            blockers = preview["validation"]["blockers"]
            if blockers:
                raise CardEventDevelopmentSplitValidationError(" ".join(blockers))

            changed_ids = {item["recording_id"] for item in preview["affected_recordings"]}
            partitions = {partition: list(current[partition]) for partition in ALL_PARTITIONS}
            for partition in ALL_PARTITIONS:
                partitions[partition] = [
                    value for value in partitions[partition] if value not in changed_ids
                ]
            partitions[destination].extend(sorted(changed_ids))
            for partition in ALL_PARTITIONS:
                partitions[partition].sort()

            created_at = _now()
            version_core = {
                "schema_version": CARD_EVENT_DEVELOPMENT_SPLIT_SCHEMA_VERSION,
                "task": CARD_EVENT_TASK,
                "parent_split_version_id": current["split_version_id"],
                "parent_split_version_digest": current["split_version_digest"],
                "created_at_utc": created_at,
                "operator": operator,
                "group_key_names": list(GROUP_KEY_NAMES),
                "recordings": current["recordings"],
                **partitions,
            }
            version_digest = _digest(version_core)
            version = {
                **version_core,
                "split_version_id": f"cardevent-development-split-{version_digest[:20]}",
                "split_version_digest": version_digest,
            }
            receipt_core = {
                "schema_version": "lifecycle-receipt/v1",
                "receipt_type": CARD_EVENT_DEVELOPMENT_SPLIT_RECEIPT_TYPE,
                "operator": operator,
                "occurred_at_utc": created_at,
                "inputs": [
                    {
                        "kind": "split_version",
                        "id": current["split_version_id"],
                        "digest": current["split_version_digest"],
                    },
                    *[
                        {
                            "kind": "source_asset",
                            "id": item["source_asset_id"],
                            "digest": item["source_sha256"],
                        }
                        for item in preview["affected_recordings"]
                    ],
                ],
                "outputs": [
                    {
                        "kind": "split_version",
                        "id": version["split_version_id"],
                        "digest": version_digest,
                    }
                ],
                "dependencies": [
                    {
                        "kind": "source_asset",
                        "id": item["source_asset_id"],
                        "digest": item["source_sha256"],
                    }
                    for item in preview["affected_recordings"]
                ],
                "metadata": {
                    "task": CARD_EVENT_TASK,
                    "destination": destination,
                    "affected_recording_ids": sorted(changed_ids),
                    "parent_split_version_id": current["split_version_id"],
                    "parent_split_version_digest": current["split_version_digest"],
                },
            }
            receipt_digest = _digest(receipt_core)
            receipt = {
                **receipt_core,
                "receipt_id": f"receipt-cardevent-development-split-{receipt_digest[:20]}",
                "receipt_digest": receipt_digest,
            }
            _validate_split(version)
            _validate_receipt(receipt)
            _write_immutable_json(
                self.version_root / f"{version['split_version_id']}.json", version
            )
            _write_immutable_json(self.receipt_root / f"{receipt['receipt_id']}.json", receipt)
            _atomic_write_json(
                self.active_path,
                {
                    "schema_version": CARD_EVENT_DEVELOPMENT_SPLIT_ACTIVE_SCHEMA_VERSION,
                    "split_version_id": version["split_version_id"],
                    "split_version_digest": version_digest,
                },
            )
            return {
                "schema_version": CARD_EVENT_DEVELOPMENT_SPLIT_APPLY_SCHEMA_VERSION,
                "task": CARD_EVENT_TASK,
                "recording_id": recording_id,
                "destination": destination,
                "affected_recordings": preview["affected_recordings"],
                "split_version_id": version["split_version_id"],
                "split_version_digest": version_digest,
                "receipt_id": receipt["receipt_id"],
                "receipt_digest": receipt_digest,
                "partitions": partitions,
                "counts": _counts(partitions),
            }

    def _read_locked(
        self,
        recordings: Sequence[CardEventDevelopmentRecording],
    ) -> dict[str, Any]:
        normalized = _normalize_recordings(recordings)
        if not self.active_path.is_file():
            return _initial_split(normalized)
        pointer = _read_json(self.active_path)
        if pointer.get("schema_version") != CARD_EVENT_DEVELOPMENT_SPLIT_ACTIVE_SCHEMA_VERSION:
            raise CardEventDevelopmentSplitError("The active development split pointer is invalid.")
        version_id = pointer.get("split_version_id")
        version_digest = pointer.get("split_version_digest")
        if not isinstance(version_id, str) or not isinstance(version_digest, str):
            raise CardEventDevelopmentSplitError(
                "The active development split pointer is incomplete."
            )
        version_path = self.version_root / f"{version_id}.json"
        if not version_path.is_file():
            raise CardEventDevelopmentSplitError("The active development split version is missing.")
        version = _read_json(version_path)
        _validate_split(version)
        if (
            version["split_version_id"] != version_id
            or version["split_version_digest"] != version_digest
        ):
            raise CardEventDevelopmentSplitError("The active development split pointer is stale.")
        return _merge_recordings(version, normalized)

    def _holdout_groups(self) -> frozenset[tuple[str, str]]:
        registry = load_system_holdout_registry(
            self.workspace_root / "system-holdout-registry.json"
        )
        return sealed_group_keys(registry)


def _build_preview(
    recordings: Sequence[CardEventDevelopmentRecording],
    split: Mapping[str, Any],
    *,
    recording_id: str,
    destination: str,
    holdout_groups: frozenset[tuple[str, str]],
) -> dict[str, Any]:
    by_id = {item.recording_id: item for item in recordings}
    if recording_id not in by_id:
        raise CardEventDevelopmentSplitValidationError(
            f"Recording {recording_id} was not found in the accepted repository intake."
        )
    components = _connected_components(recordings)
    affected = components[recording_id]
    partition_by_id = _partition_by_id(split)
    current_partitions = {partition_by_id[item.recording_id] for item in affected}
    blockers: list[str] = []
    if len(current_partitions) != 1:
        blockers.append("The active development split is not group-safe for the affected group.")
    current_partition = next(iter(current_partitions), "unassigned")
    if current_partition == destination:
        blockers.append(f"The affected group is already assigned to {destination}.")
    if "test" in current_partitions:
        blockers.append("The affected group touches the read-only test partition.")
    group_keys = sorted({key for item in affected for key in item.group_keys})
    held_out = sorted(set(group_keys) & holdout_groups)
    if held_out:
        blockers.append("The affected group touches the read-only system holdout.")

    for item in affected:
        missing = sorted(set(GROUP_KEY_NAMES) - {name for name, _ in item.group_keys})
        if missing:
            blockers.append(
                f"Missing leakage-group data for {item.recording_id}: {', '.join(missing)}."
            )
        if not item.task_selected:
            blockers.append(f"CardEvent task is not selected for {item.recording_id}.")
        if item.retention_state != "active":
            blockers.append(
                f"Source {item.source_asset_id} is {item.retention_state} and cannot be assigned."
            )
        if item.review_state != "completed":
            blockers.append(
                f"Full-recording CardEvent review is incomplete for {item.recording_id}."
            )
        if destination != "unassigned" and destination not in item.allowed_uses:
            blockers.append(f"Source {item.source_asset_id} does not allow {destination} use.")
    blockers = list(dict.fromkeys(blockers))

    proposed = {partition: list(split[partition]) for partition in ALL_PARTITIONS}
    affected_ids = {item.recording_id for item in affected}
    for partition in ALL_PARTITIONS:
        proposed[partition] = [value for value in proposed[partition] if value not in affected_ids]
    proposed[destination].extend(sorted(affected_ids))
    for partition in ALL_PARTITIONS:
        proposed[partition].sort()
    affected_recordings = [
        {
            "recording_id": item.recording_id,
            "source_asset_id": item.source_asset_id,
            "source_sha256": item.source_sha256,
            "current_partition": partition_by_id[item.recording_id],
            "group_keys": [list(key) for key in sorted(item.group_keys)],
        }
        for item in sorted(affected, key=lambda value: value.recording_id)
    ]
    core = {
        "schema_version": CARD_EVENT_DEVELOPMENT_SPLIT_PREVIEW_SCHEMA_VERSION,
        "task": CARD_EVENT_TASK,
        "recording_id": recording_id,
        "destination": destination,
        "active_split_version_id": split["split_version_id"],
        "active_split_digest": split["split_version_digest"],
        "affected_recordings": affected_recordings,
        "affected_group_keys": [list(key) for key in group_keys],
        "validation": {"valid": not blockers, "blockers": blockers},
        "current_counts": _counts({partition: split[partition] for partition in ALL_PARTITIONS}),
        "proposed_counts": _counts(proposed),
    }
    return {**core, "preview_digest": _digest(core)}


def _initial_split(
    recordings: Sequence[CardEventDevelopmentRecording],
) -> dict[str, Any]:
    entries = [_recording_entry(item) for item in recordings]
    core = {
        "schema_version": CARD_EVENT_DEVELOPMENT_SPLIT_SCHEMA_VERSION,
        "task": CARD_EVENT_TASK,
        "parent_split_version_id": None,
        "parent_split_version_digest": None,
        "created_at_utc": "1970-01-01T00:00:00.000Z",
        "operator": "system",
        "group_key_names": list(GROUP_KEY_NAMES),
        "recordings": entries,
        "train": [],
        "validation": [],
        "test": [],
        "unassigned": sorted(item.recording_id for item in recordings),
    }
    digest = _digest(core)
    return {
        **core,
        "split_version_id": "cardevent-development-split-initial",
        "split_version_digest": digest,
    }


def _merge_recordings(
    split: Mapping[str, Any],
    recordings: Sequence[CardEventDevelopmentRecording],
) -> dict[str, Any]:
    entries_by_id = {item["recording_id"]: item for item in split["recordings"]}
    for item in recordings:
        existing = entries_by_id.get(item.recording_id)
        if existing is None:
            continue
        if (
            existing["source_asset_id"] != item.source_asset_id
            or existing["source_sha256"] != item.source_sha256
            or existing["group_keys"] != [list(key) for key in item.group_keys]
        ):
            raise CardEventDevelopmentSplitError(
                "The active development split does not match immutable recording facts for "
                f"{item.recording_id}."
            )
    known = set(entries_by_id)
    additions = [item for item in recordings if item.recording_id not in known]
    if not additions:
        return dict(split)
    result = {key: value for key, value in split.items()}
    result["recordings"] = [*split["recordings"], *[_recording_entry(item) for item in additions]]
    result["recordings"].sort(key=lambda item: item["recording_id"])
    result["unassigned"] = [
        *split["unassigned"],
        *(item.recording_id for item in additions),
    ]
    result["unassigned"].sort()
    return result


def _normalize_recordings(
    recordings: Sequence[CardEventDevelopmentRecording],
) -> tuple[CardEventDevelopmentRecording, ...]:
    by_id: dict[str, CardEventDevelopmentRecording] = {}
    for item in recordings:
        if not isinstance(item, CardEventDevelopmentRecording):
            raise CardEventDevelopmentSplitError("Development split recording facts are invalid.")
        _validate_identifier(item.recording_id, "recording_id")
        _validate_identifier(item.source_asset_id, "source_asset_id")
        _validate_digest(item.source_sha256, "source_sha256")
        if item.recording_id in by_id:
            raise CardEventDevelopmentSplitError("Development split recording IDs must be unique.")
        keys = tuple(sorted(set(item.group_keys)))
        for name, value in keys:
            if name not in GROUP_KEY_NAMES or not value:
                raise CardEventDevelopmentSplitError("Development split group keys are invalid.")
        by_id[item.recording_id] = CardEventDevelopmentRecording(
            recording_id=item.recording_id,
            source_asset_id=item.source_asset_id,
            source_sha256=item.source_sha256,
            source_permission=item.source_permission,
            allowed_uses=tuple(sorted(set(item.allowed_uses))),
            retention_state=item.retention_state,
            task_selected=bool(item.task_selected),
            review_state=item.review_state,
            group_keys=keys,
            review_event_count=max(0, item.review_event_count),
        )
    return tuple(by_id[key] for key in sorted(by_id))


def _recording_entry(item: CardEventDevelopmentRecording) -> dict[str, Any]:
    return {
        "recording_id": item.recording_id,
        "source_asset_id": item.source_asset_id,
        "source_sha256": item.source_sha256,
        "group_keys": [list(key) for key in item.group_keys],
    }


def _connected_components(
    recordings: Sequence[CardEventDevelopmentRecording],
) -> dict[str, tuple[CardEventDevelopmentRecording, ...]]:
    parent = {item.recording_id: item.recording_id for item in recordings}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    first_by_key: dict[tuple[str, str], str] = {}
    for item in recordings:
        for key in item.group_keys:
            previous = first_by_key.setdefault(key, item.recording_id)
            union(previous, item.recording_id)
    grouped: dict[str, list[CardEventDevelopmentRecording]] = {}
    for item in recordings:
        grouped.setdefault(find(item.recording_id), []).append(item)
    return {
        item.recording_id: tuple(sorted(group, key=lambda value: value.recording_id))
        for group in grouped.values()
        for item in group
    }


def _partition_by_id(split: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for partition in ALL_PARTITIONS:
        for recording_id in split[partition]:
            if recording_id in result:
                raise CardEventDevelopmentSplitError(
                    "The active development split assigns a recording more than once."
                )
            result[recording_id] = partition
    return result


def _validate_split(split: Mapping[str, Any]) -> None:
    if split.get("schema_version") != CARD_EVENT_DEVELOPMENT_SPLIT_SCHEMA_VERSION:
        raise CardEventDevelopmentSplitError("The development split schema is unsupported.")
    if split.get("task") != CARD_EVENT_TASK:
        raise CardEventDevelopmentSplitError("The development split task is invalid.")
    if split.get("group_key_names") != list(GROUP_KEY_NAMES):
        raise CardEventDevelopmentSplitError("The development split group keys are invalid.")
    recordings = split.get("recordings")
    if not isinstance(recordings, list) or not recordings:
        raise CardEventDevelopmentSplitError("The development split has no recording entries.")
    ids: set[str] = set()
    for entry in recordings:
        if not isinstance(entry, Mapping):
            raise CardEventDevelopmentSplitError(
                "The development split recording entry is invalid."
            )
        recording_id = entry.get("recording_id")
        if not isinstance(recording_id, str) or not recording_id or recording_id in ids:
            raise CardEventDevelopmentSplitError("The development split recording IDs are invalid.")
        ids.add(recording_id)
        group_keys = entry.get("group_keys")
        if not isinstance(group_keys, list):
            raise CardEventDevelopmentSplitError("The development split group keys are invalid.")
        source_asset_id = entry.get("source_asset_id")
        source_sha256 = entry.get("source_sha256")
        _validate_identifier(recording_id, "recording_id")
        _validate_identifier(source_asset_id, "source_asset_id")
        _validate_digest(source_sha256, "source_sha256")
        for raw_key in group_keys:
            if (
                not isinstance(raw_key, list)
                or len(raw_key) != 2
                or raw_key[0] not in GROUP_KEY_NAMES
                or not isinstance(raw_key[1], str)
                or not raw_key[1]
            ):
                raise CardEventDevelopmentSplitError(
                    "The development split group keys are invalid."
                )
    for partition in ALL_PARTITIONS:
        values = split.get(partition)
        if not isinstance(values, list) or any(
            not isinstance(recording_id, str) for recording_id in values
        ):
            raise CardEventDevelopmentSplitError(
                "The development split partition entries are invalid."
            )
    partition_ids = _partition_by_id(split)
    if set(partition_ids) != ids:
        raise CardEventDevelopmentSplitError(
            "The development split must assign every recording once."
        )
    group_partition: dict[tuple[str, str], str] = {}
    for entry in recordings:
        partition = partition_ids[entry["recording_id"]]
        for raw_key in entry["group_keys"]:
            key = (raw_key[0], raw_key[1])
            previous = group_partition.get(key)
            if previous is not None and previous != partition:
                raise CardEventDevelopmentSplitError(
                    f"The development split crosses group {key[0]}:{key[1]} between partitions."
                )
            group_partition[key] = partition
    _validate_identifier(split.get("split_version_id"), "split_version_id")
    core = {
        key: value
        for key, value in split.items()
        if key not in {"split_version_id", "split_version_digest"}
    }
    if split.get("split_version_digest") != _digest(core):
        raise CardEventDevelopmentSplitError("The development split digest is invalid.")


def _validate_receipt(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema_version") != "lifecycle-receipt/v1":
        raise CardEventDevelopmentSplitError("The development split receipt schema is invalid.")
    _validate_identifier(receipt.get("receipt_id"), "receipt_id")
    _validate_digest(receipt.get("receipt_digest"), "receipt_digest")
    core = {
        key: value
        for key, value in receipt.items()
        if key not in {"receipt_id", "receipt_digest"}
    }
    if receipt["receipt_digest"] != _digest(core):
        raise CardEventDevelopmentSplitError("The development split receipt digest is invalid.")


def _counts(partitions: Mapping[str, Sequence[str]]) -> dict[str, int]:
    return {partition: len(partitions[partition]) for partition in ALL_PARTITIONS}


def _validate_destination(destination: str) -> None:
    if destination not in DEVELOPMENT_PARTITIONS:
        raise CardEventDevelopmentSplitError(
            "Development partition must be train, validation, or unassigned."
        )


def _validate_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(char in value for char in "/\\\x00"):
        raise CardEventDevelopmentSplitError(f"{field} must be a safe non-empty identifier.")
    return value


def _validate_digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _DIGEST_LENGTH
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise CardEventDevelopmentSplitError(f"{field} must be a lower-case SHA-256 digest.")
    return value


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventDevelopmentSplitError(
            f"Could not read development split artifact {path}."
        ) from error
    if not isinstance(value, dict):
        raise CardEventDevelopmentSplitError(f"Development split artifact {path} is not an object.")
    return value


def _write_immutable_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise CardEventDevelopmentSplitError(f"Immutable artifact already exists: {path}")
        return
    with path.open("x", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(raw_path)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def _split_lock(path: Path, *, exclusive: bool) -> Iterator[None]:
    """Serialize preview reads and publication against one local active pointer."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:
        yield
        return
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


__all__ = [
    "ALL_PARTITIONS",
    "CARD_EVENT_DEVELOPMENT_SPLIT_ACTIVE_SCHEMA_VERSION",
    "CARD_EVENT_DEVELOPMENT_SPLIT_APPLY_SCHEMA_VERSION",
    "CARD_EVENT_DEVELOPMENT_SPLIT_PREVIEW_SCHEMA_VERSION",
    "CARD_EVENT_DEVELOPMENT_SPLIT_SCHEMA_VERSION",
    "CardEventDevelopmentRecording",
    "CardEventDevelopmentSplitConflict",
    "CardEventDevelopmentSplitError",
    "CardEventDevelopmentSplitStore",
    "CardEventDevelopmentSplitValidationError",
    "DEVELOPMENT_PARTITIONS",
    "GROUP_KEY_NAMES",
]
