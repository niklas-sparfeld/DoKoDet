"""Freeze and validate immutable CardEventNet dataset versions."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .cardevent_readiness import build_cardeventnet_readiness
from .holdout import load_system_holdout_registry, sealed_group_keys
from .source_exclusion import (
    LEGACY_DEVICE_RECORDING_ID_SET,
    LEGACY_DEVICE_SOURCE_ASSET_ID_SET,
    SourceExclusionError,
    ensure_source_allowed,
    read_legacy_device_exclusion,
)

CARD_EVENTNET_DATASET_SCHEMA_VERSION = "cardeventnet-dataset/v1"
CARD_EVENTNET_SPLIT_SCHEMA_VERSION = "cardeventnet-split/v1"
CARD_EVENTNET_COVERAGE_SCHEMA_VERSION = "cardeventnet-coverage/v1"
CARD_EVENTNET_FREEZE_REPORT_SCHEMA_VERSION = "cardeventnet-freeze-report/v1"
CARD_EVENTNET_FREEZE_RECEIPT_SCHEMA_VERSION = "cardeventnet-freeze-receipt/v1"
CARD_EVENTNET_TASK = "cardevent_event_detection"
PARTITIONS = ("train", "validation", "test")
GROUP_KEY_NAMES = ("game_id", "session_id", "source_lineage", "table_setup")
REQUIRED_GROUP_KEY_NAMES = ("session_id", "source_lineage", "table_setup")
VALID_SOURCE_PERMISSIONS = {
    "training_only",
    "training_and_evaluation",
    "project_use",
    "unrestricted",
}
_DIGEST_LENGTH = 64


class CardEventNetDatasetFreezeError(ValueError):
    """The CardEventNet inputs are not safe to freeze."""

    def __init__(self, message: str, *, report: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report = dict(report) if report is not None else None


def build_cardeventnet_freeze_report(
    readiness: Mapping[str, Any],
    split: Mapping[str, Any] | None,
    *,
    holdout_groups: Sequence[tuple[str, str]] = (),
) -> dict[str, Any]:
    """Build a deterministic preflight report from readiness and split facts."""

    raw_records = readiness.get("recordings", [])
    records = [dict(item) for item in raw_records if isinstance(item, Mapping)]
    records = [
        item
        for item in records
        if item.get("recording_id") not in LEGACY_DEVICE_RECORDING_ID_SET
        and item.get("source_asset_id") not in LEGACY_DEVICE_SOURCE_ASSET_ID_SET
    ]
    records.sort(key=lambda item: str(item.get("recording_id", "")))
    by_id = {
        item["recording_id"]: item
        for item in records
        if isinstance(item.get("recording_id"), str)
    }
    blockers: list[str] = []
    queue = readiness.get("review_queue", [])
    queued_ids = sorted(
        item.get("recording_id")
        for item in queue
        if isinstance(item, Mapping) and isinstance(item.get("recording_id"), str)
    )
    if queued_ids:
        blockers.append("review readiness is incomplete: " + ", ".join(queued_ids))

    eligible: dict[str, dict[str, Any]] = {}
    for record in records:
        recording_id = record.get("recording_id")
        if not isinstance(recording_id, str):
            blockers.append("readiness contains a recording without a recording ID")
            continue
        if record.get("primary_state") != "review_complete":
            blockers.append(
                f"recording {recording_id} is not review-complete "
                f"({record.get('primary_state', 'unknown')})"
            )
        for blocker in record.get("blockers", []):
            if isinstance(blocker, str):
                blockers.append(f"recording {recording_id}: {blocker}")
        group_keys = _group_keys(record)
        missing = _missing_group_keys(record, group_keys)
        has_readiness_group_blocker = any(
            isinstance(blocker, str) and blocker.startswith("missing group metadata:")
            for blocker in record.get("blockers", [])
        )
        if missing and not has_readiness_group_blocker:
            blockers.append(
                f"recording {recording_id} is missing group metadata: {', '.join(missing)}"
            )
        if record.get("retention_state") not in {None, "active"}:
            blockers.append(
                f"recording {recording_id} source retention state is not active"
            )
        if record.get("source_exists") is False:
            blockers.append(f"recording {recording_id} source video is missing")
        permission = record.get("source_permission")
        if permission is not None and permission not in VALID_SOURCE_PERMISSIONS:
            blockers.append(f"recording {recording_id} has invalid source permission")
        allowed = _allowed_partitions(record)
        if not allowed:
            blockers.append(f"recording {recording_id} has no allowed dataset partition")
        progress = record.get("review_progress")
        if not isinstance(progress, Mapping) or progress.get("coverage_complete") is not True:
            blockers.append(f"recording {recording_id} has incomplete full-recording coverage")
        revision = record.get("event_revision")
        if not isinstance(revision, Mapping) or not revision.get("revision_id"):
            blockers.append(f"recording {recording_id} has no completed event revision")
        elif revision.get("source_sha256") not in {None, record.get("source_sha256")}:
            blockers.append(f"recording {recording_id} event revision source digest differs")
        elif (
            not isinstance(revision.get("duration_us"), int)
            or revision.get("duration_us", 0) <= 0
        ):
            blockers.append(f"recording {recording_id} event revision duration is missing")
        if (
            record.get("primary_state") == "review_complete"
            and not record.get("blockers")
            and not missing
            and isinstance(revision, Mapping)
        ):
            eligible[recording_id] = record

    normalised_split = _normalise_split(split)
    if normalised_split is None:
        blockers.append(
            "active group-safe development split is missing; assign eligible groups to train "
            "and validation"
        )
        partitions = {partition: [] for partition in (*PARTITIONS, "unassigned")}
        split_info: dict[str, Any] = {"state": "missing", "partitions": partitions}
    else:
        split_info = normalised_split
        if normalised_split["state"] != "valid":
            blockers.append("active group-safe development split is invalid")
        partitions = normalised_split["partitions"]

    partition_by_id: dict[str, str] = {}
    for partition, values in partitions.items():
        for recording_id in values:
            if recording_id in partition_by_id:
                blockers.append(f"split assigns recording more than once: {recording_id}")
            partition_by_id[recording_id] = partition
            if recording_id not in by_id:
                blockers.append(f"split contains unknown recording: {recording_id}")
            elif recording_id not in eligible:
                blockers.append(f"split includes non-eligible recording: {recording_id}")

    for recording_id in sorted(eligible):
        if recording_id not in partition_by_id:
            blockers.append(f"eligible recording is missing from the split: {recording_id}")

    group_partition: dict[tuple[str, str], str] = {}
    for recording_id, partition in partition_by_id.items():
        record = by_id.get(recording_id)
        if record is None:
            continue
        for group_key in _group_keys(record):
            previous = group_partition.get(group_key)
            if previous is not None and previous != partition:
                blockers.append(
                    f"split crosses leakage group {group_key[0]}:{group_key[1]} "
                    f"between {previous} and {partition}"
                )
            group_partition[group_key] = partition

    held_out = set(holdout_groups)
    for group_key, partition in sorted(group_partition.items()):
        if group_key in held_out:
            blockers.append(
                f"split assigns system holdout group {group_key[0]}:{group_key[1]} to {partition}"
            )

    for partition in PARTITIONS:
        if not partitions.get(partition):
            if partition == "test":
                blockers.append(
                    "independent sealed test source-lineage group is required; collect, migrate, "
                    "annotate, and assign a new group to test"
                )
            else:
                blockers.append(f"{partition} partition is empty")

    test_groups = {
        group_key
        for recording_id in partitions.get("test", [])
        for group_key in _group_keys(by_id.get(recording_id, {}))
    }
    development_groups = {
        group_key
        for partition in ("train", "validation")
        for recording_id in partitions.get(partition, [])
        for group_key in _group_keys(by_id.get(recording_id, {}))
    }
    for group_key in sorted(test_groups & development_groups):
        blockers.append(
            f"test group is not independent from development: {group_key[0]}:{group_key[1]}"
        )

    for recording_id, partition in sorted(partition_by_id.items()):
        record = by_id.get(recording_id)
        if record is None:
            continue
        if partition not in _allowed_partitions(record):
            blockers.append(f"recording {recording_id} does not allow {partition} use")

    blockers = list(dict.fromkeys(blockers))
    entries = [
        _dataset_entry(by_id[recording_id], partition)
        for partition in PARTITIONS
        for recording_id in sorted(partitions.get(partition, []))
        if recording_id in by_id
    ]
    coverage = _coverage(entries)
    state = "ready" if not blockers else "blocked"
    core: dict[str, Any] = {
        "schema_version": CARD_EVENTNET_FREEZE_REPORT_SCHEMA_VERSION,
        "task": CARD_EVENTNET_TASK,
        "state": state,
        "readiness_digest": readiness.get("report_digest"),
        "split": split_info,
        "test_sealed": state == "ready",
        "eligible_recordings": sorted(eligible),
        "entries": entries,
        "coverage": coverage,
        "blockers": blockers,
        "next_action": (
            "freeze the immutable dataset version and retain its receipt."
            if state == "ready"
            else "repair the listed inputs, then rerun cardevent freeze."
        ),
    }
    core["report_digest"] = _digest(core)
    return core


def build_cardeventnet_freeze(
    repository_root: str | Path,
    *,
    intake_root: str | Path | None = None,
    operations_root: str | Path | None = None,
) -> dict[str, Any]:
    """Build the freeze report from the repository's canonical data owners."""

    repository = Path(repository_root).expanduser().resolve()
    operations = _resolve(repository, operations_root or Path("data/operations"))
    readiness = build_cardeventnet_readiness(
        repository,
        intake_root=intake_root,
        operations_root=operations,
    ).to_mapping()
    records = [
        dict(item)
        for item in readiness.get("recordings", [])
        if isinstance(item, Mapping) and item.get("migration_state") == "migrated"
    ]
    try:
        exclusion, exclusion_digest = read_legacy_device_exclusion(repository, None)
    except SourceExclusionError as error:
        raise CardEventNetDatasetFreezeError(str(error)) from error
    diagnostic_records = [
        item
        for item in records
        if item.get("recording_id") in LEGACY_DEVICE_RECORDING_ID_SET
        or item.get("source_asset_id") in LEGACY_DEVICE_SOURCE_ASSET_ID_SET
    ]
    if diagnostic_records and exclusion is None:
        raise CardEventNetDatasetFreezeError(
            "legacy-device diagnostic-only exclusion receipt is required before a new freeze"
        )
    records = [item for item in records if item not in diagnostic_records]
    migrated_ids = {
        item["recording_id"]
        for item in records
        if isinstance(item.get("recording_id"), str)
    }
    readiness["review_queue"] = [
        dict(item)
        for item in readiness.get("review_queue", [])
        if isinstance(item, Mapping) and item.get("recording_id") in migrated_ids
    ]
    revisions = _event_revisions(repository, operations)
    for record in records:
        _enrich_record(
            repository,
            operations,
            record,
            revisions.get(record.get("recording_id"), ()),
        )
    readiness["recordings"] = records
    split = _load_active_split(operations)
    holdout_groups = _load_holdout_groups(operations)
    report = build_cardeventnet_freeze_report(
        readiness,
        split,
        holdout_groups=holdout_groups,
    )
    if exclusion is not None:
        report["diagnostic_exclusion"] = {
            "path": "data/operations/source-exclusions/legacy-device-diagnostic.json",
            "receipt_digest": exclusion.get("receipt_digest"),
            "file_sha256": exclusion_digest,
            "recording_ids": sorted(LEGACY_DEVICE_RECORDING_ID_SET),
        }
        report["report_digest"] = _digest(
            {key: value for key, value in report.items() if key != "report_digest"}
        )
    return report


def freeze_cardeventnet_dataset(
    repository_root: str | Path,
    *,
    operator: str,
    intake_root: str | Path | None = None,
    operations_root: str | Path | None = None,
) -> dict[str, Any]:
    """Publish one immutable dataset version, or raise with its exact blockers."""

    if not _safe_identifier(operator):
        raise CardEventNetDatasetFreezeError("operator must be a safe non-empty identifier")
    repository = Path(repository_root).expanduser().resolve()
    operations = _resolve(repository, operations_root or Path("data/operations"))
    report = build_cardeventnet_freeze(
        repository, intake_root=intake_root, operations_root=operations
    )
    if report["state"] != "ready":
        raise CardEventNetDatasetFreezeError(
            "CardEventNet dataset freeze is blocked: " + " ".join(report["blockers"]),
            report=report,
        )

    entries = report["entries"]
    dataset_core: dict[str, Any] = {
        "schema_version": CARD_EVENTNET_DATASET_SCHEMA_VERSION,
        "task": CARD_EVENTNET_TASK,
        "readiness_digest": report["readiness_digest"],
        "split_version_id": report["split"]["split_version_id"],
        "split_version_digest": report["split"]["split_version_digest"],
        "test_sealed": True,
        "entries": entries,
    }
    diagnostic_exclusion = report.get("diagnostic_exclusion")
    if isinstance(diagnostic_exclusion, Mapping):
        dataset_core["diagnostic_exclusion_receipt_sha256"] = diagnostic_exclusion.get(
            "receipt_digest"
        )
    dataset_digest = _digest(dataset_core)
    dataset_id = f"cardeventnet-dataset-{dataset_digest[:20]}"
    dataset = {
        **dataset_core,
        "dataset_version_id": dataset_id,
        "dataset_version_digest": dataset_digest,
    }
    split_core: dict[str, Any] = {
        "schema_version": CARD_EVENTNET_SPLIT_SCHEMA_VERSION,
        "task": CARD_EVENTNET_TASK,
        "dataset_version_id": dataset_id,
        "dataset_version_digest": dataset_digest,
        "group_key_names": list(GROUP_KEY_NAMES),
        "train": list(report["split"]["partitions"]["train"]),
        "validation": list(report["split"]["partitions"]["validation"]),
        "test": list(report["split"]["partitions"]["test"]),
        "unassigned": list(report["split"]["partitions"].get("unassigned", [])),
        "test_sealed": True,
    }
    split_digest = _digest(split_core)
    split = {
        **split_core,
        "split_version_id": f"cardeventnet-split-{split_digest[:20]}",
        "split_version_digest": split_digest,
    }
    coverage_core = {
        "schema_version": CARD_EVENTNET_COVERAGE_SCHEMA_VERSION,
        "task": CARD_EVENTNET_TASK,
        "dataset_version_id": dataset_id,
        "dataset_version_digest": dataset_digest,
        "partitions": report["coverage"],
    }
    coverage_digest = _digest(coverage_core)
    coverage = {**coverage_core, "coverage_digest": coverage_digest}
    receipt_core = {
        "schema_version": CARD_EVENTNET_FREEZE_RECEIPT_SCHEMA_VERSION,
        "receipt_type": "cardeventnet_dataset_freeze",
        "operator": operator,
        "inputs": [
            {
                "kind": "readiness_report",
                "digest": report["readiness_digest"],
            },
            {
                "kind": "development_split",
                "id": report["split"]["split_version_id"],
                "digest": report["split"]["split_version_digest"],
            },
        ],
        "outputs": [
            {"kind": "dataset", "id": dataset_id, "digest": dataset_digest},
            {"kind": "split", "id": split["split_version_id"], "digest": split_digest},
            {"kind": "coverage", "digest": coverage_digest},
        ],
    }
    if isinstance(diagnostic_exclusion, Mapping):
        receipt_core["inputs"].append(
            {
                "kind": "diagnostic_only_source_exclusion",
                "digest": diagnostic_exclusion.get("receipt_digest"),
            }
        )
    receipt_digest = _digest(receipt_core)
    receipt = {
        **receipt_core,
        "receipt_id": f"receipt-cardeventnet-freeze-{receipt_digest[:20]}",
        "receipt_digest": receipt_digest,
    }
    destination = operations / "cardevent-datasets" / dataset_id
    _write_immutable_json(destination / "dataset.json", dataset)
    _write_immutable_json(destination / "split.json", split)
    _write_immutable_json(destination / "coverage.json", coverage)
    _write_immutable_json(destination / "receipt.json", receipt)
    return {
        "state": "frozen",
        "dataset_version_id": dataset_id,
        "dataset_version_digest": dataset_digest,
        "split_version_id": split["split_version_id"],
        "split_version_digest": split_digest,
        "coverage_digest": coverage_digest,
        "receipt_id": receipt["receipt_id"],
        "receipt_digest": receipt_digest,
        "path": _relative(destination, repository),
        "coverage": report["coverage"],
    }


def render_cardeventnet_freeze_human(result: Mapping[str, Any]) -> str:
    """Render a concise freeze preflight or publication result."""

    lines = [
        "CardEventNet dataset freeze",
        f"state: {result.get('state')}",
    ]
    if result.get("state") == "frozen":
        lines.extend(
            [
                f"dataset version: {result['dataset_version_id']}",
                f"dataset digest: {result['dataset_version_digest']}",
                f"split: {result['split_version_id']}",
                f"path: {result['path']}",
            ]
        )
    else:
        blockers = result.get("blockers", [])
        lines.append("blockers:")
        lines.extend(f"  - {blocker}" for blocker in blockers)
        lines.append(f"next action: {result.get('next_action')}")
    return "\n".join(lines) + "\n"


def validate_cardeventnet_dataset_artifacts(
    repository_root: str | Path,
    *,
    operations_root: str | Path | None = None,
) -> tuple[str, ...]:
    """Return validation failures for all published CardEventNet dataset versions."""

    repository = Path(repository_root).expanduser().resolve()
    operations = _resolve(repository, operations_root or Path("data/operations"))
    root = operations / "cardevent-datasets"
    if not root.exists():
        return ()
    if not root.is_dir():
        return ("cardevent-datasets is not a directory",)
    failures: list[str] = []
    for dataset_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        try:
            dataset = _read_object(dataset_dir / "dataset.json")
            split = _read_object(dataset_dir / "split.json")
            coverage = _read_object(dataset_dir / "coverage.json")
            receipt = _read_object(dataset_dir / "receipt.json")
            if dataset is None or split is None or coverage is None or receipt is None:
                raise CardEventNetDatasetFreezeError(
                    "dataset version is missing a required artifact"
                )
            _validate_dataset(dataset, split, coverage, receipt, repository)
        except (OSError, CardEventNetDatasetFreezeError, ValueError) as error:
            failures.append(f"{_relative(dataset_dir, repository)}: {error}")
    return tuple(failures)


def _dataset_entry(record: Mapping[str, Any], partition: str) -> dict[str, Any]:
    revision = record.get("event_revision")
    progress = record.get("review_progress")
    return {
        "recording_id": record["recording_id"],
        "source_asset_id": record.get("source_asset_id"),
        "source_path": record.get("source_path"),
        "source_sha256": record.get("source_sha256"),
        "source_permission": record.get("source_permission"),
        "allowed_uses": _allowed_partitions(record),
        "retention_state": record.get("retention_state", "active"),
        "content_type": record.get("content_type"),
        "group_keys": [list(key) for key in _group_keys(record)],
        "group_metadata_basis": record.get("group_metadata_basis", {}),
        "partition": partition,
        "event_revision_id": revision.get("revision_id") if isinstance(revision, Mapping) else None,
        "event_revision_manifest_path": (
            revision.get("manifest_path") if isinstance(revision, Mapping) else None
        ),
        "event_revision_manifest_sha256": (
            revision.get("manifest_sha256") if isinstance(revision, Mapping) else None
        ),
        "event_revision_content_path": (
            revision.get("content_path") if isinstance(revision, Mapping) else None
        ),
        "event_revision_content_sha256": (
            revision.get("content_sha256") if isinstance(revision, Mapping) else None
        ),
        "event_count": revision.get("event_count", 0) if isinstance(revision, Mapping) else 0,
        "duration_us": revision.get("duration_us") if isinstance(revision, Mapping) else None,
        "review_coverage": dict(progress) if isinstance(progress, Mapping) else {},
        "task": CARD_EVENTNET_TASK,
    }


def _coverage(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for partition in PARTITIONS:
        selected = [item for item in entries if item.get("partition") == partition]
        result[partition] = {
            "recording_ids": sorted(str(item["recording_id"]) for item in selected),
            "recording_count": len(selected),
            "event_count": sum(
                item.get("event_count", 0)
                if isinstance(item.get("event_count", 0), int)
                else 0
                for item in selected
            ),
            "duration_us": sum(
                item.get("duration_us", 0)
                if isinstance(item.get("duration_us", 0), int)
                else 0
                for item in selected
            ),
            "full_recording_coverage": all(
                item.get("review_coverage", {}).get("coverage_complete") is True
                for item in selected
            ),
        }
    return result


def _group_keys(record: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    raw = record.get("group_keys")
    if isinstance(raw, list):
        result = {
            (item[0], item[1])
            for item in raw
            if isinstance(item, (list, tuple))
            and len(item) == 2
            and item[0] in GROUP_KEY_NAMES
            and isinstance(item[1], str)
            and item[1]
        }
        return tuple(sorted(result))
    source = record.get("source_metadata")
    source = source if isinstance(source, Mapping) else record
    return tuple(
        sorted(
            (name, source[name])
            for name in GROUP_KEY_NAMES
            if isinstance(source.get(name), str) and source.get(name)
        )
    )


def _missing_group_keys(
    record: Mapping[str, Any], group_keys: Sequence[tuple[str, str]]
) -> list[str]:
    present = {name for name, _ in group_keys}
    required = list(REQUIRED_GROUP_KEY_NAMES)
    source = record.get("source_metadata")
    source = source if isinstance(source, Mapping) else record
    if source.get("content_type") == "real_game":
        required.append("game_id")
    return [name for name in required if name not in present]


def _allowed_partitions(record: Mapping[str, Any]) -> list[str]:
    raw = record.get("allowed_partitions")
    if not isinstance(raw, list):
        raw = record.get("allowed_uses")
    if not isinstance(raw, list):
        source = record.get("source_metadata")
        raw = source.get("allowed_uses") if isinstance(source, Mapping) else []
    return sorted({item for item in raw if item in PARTITIONS})


def _normalise_split(split: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(split, Mapping):
        return None
    raw_partitions = (
        split.get("partitions") if isinstance(split.get("partitions"), Mapping) else split
    )
    partitions: dict[str, list[str]] = {}
    for partition in (*PARTITIONS, "unassigned"):
        raw = raw_partitions.get(partition, []) if isinstance(raw_partitions, Mapping) else []
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            return {
                "state": "invalid",
                "partitions": {name: [] for name in (*PARTITIONS, "unassigned")},
            }
        partitions[partition] = sorted(raw)
    if not _safe_identifier(split.get("split_version_id")) or not _valid_digest(
        split.get("split_version_digest")
    ):
        return {"state": "invalid", "partitions": partitions}
    return {
        "state": "valid",
        "split_version_id": split.get("split_version_id"),
        "split_version_digest": split.get("split_version_digest"),
        "partitions": partitions,
    }


def _load_active_split(operations: Path) -> dict[str, Any] | None:
    active = _read_object(operations / "cardevent-development-split" / "active.json")
    if active is None:
        return None
    version_id = active.get("split_version_id")
    if not isinstance(version_id, str):
        return {"state": "invalid"}
    version = _read_object(
        operations / "cardevent-development-split" / "versions" / f"{version_id}.json"
    )
    if version is None:
        return {"state": "invalid"}
    if version.get("split_version_digest") != active.get("split_version_digest"):
        return {"state": "invalid"}
    version_core = {
        key: value for key, value in version.items() if key != "split_version_digest"
    }
    version_core.pop("split_version_id", None)
    if _digest(version_core) != version.get("split_version_digest"):
        return {"state": "invalid"}
    return version


def _load_holdout_groups(operations: Path) -> frozenset[tuple[str, str]]:
    registry_path = operations / "system-holdout-registry.json"
    if not registry_path.is_file():
        return frozenset()
    registry = load_system_holdout_registry(registry_path)
    return sealed_group_keys(registry)


def _event_revisions(repository: Path, operations: Path) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    root = operations / "pipeline" / "revisions"
    if not root.is_dir():
        return result
    for manifest_path in sorted(root.rglob("manifest.json"), key=lambda path: path.as_posix()):
        manifest = _read_object(manifest_path)
        if not manifest or manifest.get("content_type") != "events":
            continue
        recording_id = manifest.get("recording_id")
        revision_id = manifest.get("revision_id")
        if not isinstance(recording_id, str) or not isinstance(revision_id, str):
            continue
        content_path = manifest_path.parent / "content.json"
        content = _read_object(content_path)
        source = manifest.get("source")
        duration_us = source.get("duration_us") if isinstance(source, Mapping) else None
        result.setdefault(recording_id, []).append(
            {
                "revision_id": revision_id,
                "manifest_path": _relative(manifest_path, repository),
                "manifest_sha256": _sha256_file(manifest_path),
                "content_path": _relative(content_path, repository),
                "content_sha256": _sha256_file(content_path) if content_path.is_file() else None,
                "source_sha256": (
                    source.get("video_sha256") if isinstance(source, Mapping) else None
                ),
                "duration_us": duration_us,
                "event_count": len(content.get("events", [])) if content else 0,
            }
        )
    for entries in result.values():
        entries.sort(key=lambda item: item["revision_id"])
    return result


def _enrich_record(
    repository: Path,
    operations: Path,
    record: dict[str, Any],
    revisions: Sequence[Mapping[str, Any]],
) -> None:
    source_path = record.get("source_path")
    source_record_path: Path | None = None
    if isinstance(source_path, str):
        video_path = _resolve(repository, source_path)
        source_record_path = video_path.parent.parent / "source-record.json"
    if source_record_path is None:
        source_record_path = repository / "data" / "intake" / "recordings" / str(
            record.get("recording_id", "")
        ) / "source-record.json"
    source = _read_object(source_record_path) or {}
    recording_id = record.get("recording_id")
    imported_metadata = (
        _read_object(
            operations
            / "cardeventnet-imports"
            / recording_id
            / "metadata.json"
        )
        if isinstance(recording_id, str)
        else None
    )
    group_metadata_basis: dict[str, str] = {}
    if source.get("content_type") == "real_game" and not source.get("game_id"):
        game_id = (
            imported_metadata.get("game_id") if isinstance(imported_metadata, Mapping) else None
        )
        if isinstance(game_id, str) and game_id:
            source["game_id"] = game_id
            group_metadata_basis["game_id"] = "preserved_legacy_metadata"
    if not source.get("source_lineage"):
        session_id = source.get("session_id")
        if isinstance(session_id, str) and session_id:
            source["source_lineage"] = f"session-lineage-{session_id}"
            group_metadata_basis["source_lineage"] = "recorded_session_id"
    record["source_asset_id"] = source.get("source_asset_id")
    record["source_permission"] = source.get("source_permission")
    record["allowed_uses"] = source.get("allowed_uses", record.get("allowed_partitions", []))
    record["retention_state"] = source.get("retention_state")
    record["content_type"] = source.get("content_type")
    record["source_metadata"] = source
    record["group_metadata_basis"] = group_metadata_basis
    record["group_keys"] = [list(key) for key in _group_keys({"source_metadata": source})]
    if not _missing_group_keys(record, _group_keys({"source_metadata": source})):
        record["blockers"] = [
            blocker
            for blocker in record.get("blockers", [])
            if not isinstance(blocker, str) or not blocker.startswith("missing group metadata:")
        ]
    selected_id = record.get("maintained_reference", {}).get("selected_completed_revision_id")
    if not isinstance(selected_id, str):
        selected_id = record.get("maintained_reference", {}).get("source_revision_id")
    record["event_revision"] = next(
        (dict(item) for item in revisions if item.get("revision_id") == selected_id),
        None,
    )
    record["source_exists"] = (
        isinstance(source_path, str) and _resolve(repository, source_path).is_file()
    )


def _validate_dataset(
    dataset: Mapping[str, Any],
    split: Mapping[str, Any],
    coverage: Mapping[str, Any],
    receipt: Mapping[str, Any],
    repository: Path,
) -> None:
    if dataset.get("schema_version") != CARD_EVENTNET_DATASET_SCHEMA_VERSION:
        raise CardEventNetDatasetFreezeError("dataset schema is unsupported")
    if split.get("schema_version") != CARD_EVENTNET_SPLIT_SCHEMA_VERSION:
        raise CardEventNetDatasetFreezeError("split schema is unsupported")
    if coverage.get("schema_version") != CARD_EVENTNET_COVERAGE_SCHEMA_VERSION:
        raise CardEventNetDatasetFreezeError("coverage schema is unsupported")
    if receipt.get("schema_version") != CARD_EVENTNET_FREEZE_RECEIPT_SCHEMA_VERSION:
        raise CardEventNetDatasetFreezeError("freeze receipt schema is unsupported")
    dataset_id = dataset.get("dataset_version_id")
    dataset_digest = dataset.get("dataset_version_digest")
    if not _safe_identifier(dataset_id) or not _valid_digest(dataset_digest):
        raise CardEventNetDatasetFreezeError("dataset identity is invalid")
    dataset_core = {key: value for key, value in dataset.items() if key != "dataset_version_digest"}
    dataset_core.pop("dataset_version_id", None)
    if _digest(dataset_core) != dataset_digest:
        raise CardEventNetDatasetFreezeError("dataset digest is invalid")
    if (
        split.get("dataset_version_id") != dataset_id
        or split.get("dataset_version_digest") != dataset_digest
    ):
        raise CardEventNetDatasetFreezeError("split does not reference the dataset")
    split_digest = split.get("split_version_digest")
    split_core = {key: value for key, value in split.items() if key != "split_version_digest"}
    split_core.pop("split_version_id", None)
    if not _valid_digest(split_digest) or _digest(split_core) != split_digest:
        raise CardEventNetDatasetFreezeError("split digest is invalid")
    entries = dataset.get("entries")
    if not isinstance(entries, list):
        raise CardEventNetDatasetFreezeError("dataset entries are invalid")
    coverage_core = {key: value for key, value in coverage.items() if key != "coverage_digest"}
    if not _valid_digest(coverage.get("coverage_digest")) or _digest(coverage_core) != coverage[
        "coverage_digest"
    ]:
        raise CardEventNetDatasetFreezeError("coverage digest is invalid")
    if coverage.get("partitions") != _coverage(entries):
        raise CardEventNetDatasetFreezeError("coverage does not match dataset entries")
    receipt_digest = receipt.get("receipt_digest")
    receipt_core = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    receipt_core.pop("receipt_id", None)
    if not _valid_digest(receipt_digest) or _digest(receipt_core) != receipt_digest:
        raise CardEventNetDatasetFreezeError("freeze receipt digest is invalid")
    entries_by_id = {
        item.get("recording_id"): item for item in entries if isinstance(item, Mapping)
    }
    if len(entries_by_id) != len(entries):
        raise CardEventNetDatasetFreezeError("dataset recording IDs are not unique")
    assigned = set()
    for partition in PARTITIONS:
        values = split.get(partition)
        if not isinstance(values, list) or not values:
            raise CardEventNetDatasetFreezeError(f"{partition} partition is empty")
        for recording_id in values:
            if recording_id in assigned or recording_id not in entries_by_id:
                raise CardEventNetDatasetFreezeError("split and dataset entries disagree")
            assigned.add(recording_id)
            entry = entries_by_id[recording_id]
            if entry.get("partition") != partition:
                raise CardEventNetDatasetFreezeError("dataset entry partition is invalid")
            _validate_published_entry(
                entry,
                repository,
                enforce_source_exclusion=dataset.get("diagnostic_exclusion_receipt_sha256")
                is not None,
            )
    if assigned != set(entries_by_id):
        raise CardEventNetDatasetFreezeError("dataset contains unassigned entries")
    if split.get("test_sealed") is not True or dataset.get("test_sealed") is not True:
        raise CardEventNetDatasetFreezeError("test partition is not sealed")
    group_partition: dict[tuple[str, str], str] = {}
    for partition in PARTITIONS:
        for recording_id in split[partition]:
            for raw_key in entries_by_id[recording_id].get("group_keys", []):
                if not isinstance(raw_key, list) or len(raw_key) != 2:
                    raise CardEventNetDatasetFreezeError("dataset entry group keys are invalid")
                key = (raw_key[0], raw_key[1])
                previous = group_partition.get(key)
                if previous is not None and previous != partition:
                    raise CardEventNetDatasetFreezeError(
                        f"split crosses leakage group {key[0]}:{key[1]}"
                    )
                group_partition[key] = partition


def _validate_published_entry(
    entry: Mapping[str, Any], repository: Path, *, enforce_source_exclusion: bool = False
) -> None:
    source_path = entry.get("source_path")
    if not isinstance(source_path, str) or not _resolve(repository, source_path).is_file():
        raise CardEventNetDatasetFreezeError(
            f"source is missing for recording {entry.get('recording_id')}"
        )
    source_digest = entry.get("source_sha256")
    if (
        not _valid_digest(source_digest)
        or _sha256_file(_resolve(repository, source_path)) != source_digest
    ):
        raise CardEventNetDatasetFreezeError(
            f"source digest is invalid for recording {entry.get('recording_id')}"
        )
    if enforce_source_exclusion:
        try:
            ensure_source_allowed(
                source_asset_id=entry.get("source_asset_id"),
                source_sha256=source_digest,
                recording_id=entry.get("recording_id"),
            )
        except SourceExclusionError as error:
            raise CardEventNetDatasetFreezeError(str(error)) from error
    artifact_digests = {
        "event_revision_manifest_path": entry.get("event_revision_manifest_sha256"),
        "event_revision_content_path": entry.get("event_revision_content_sha256"),
    }
    for field, expected_digest in artifact_digests.items():
        path_value = entry.get(field)
        if not isinstance(path_value, str) or not _resolve(repository, path_value).is_file():
            raise CardEventNetDatasetFreezeError(
                f"event revision artifact is missing for recording {entry.get('recording_id')}"
            )
        if (
            not _valid_digest(expected_digest)
            or _sha256_file(_resolve(repository, path_value)) != expected_digest
        ):
            raise CardEventNetDatasetFreezeError(
                f"event revision digest is invalid for recording {entry.get('recording_id')}"
            )


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _write_immutable_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise CardEventNetDatasetFreezeError(f"immutable artifact already exists: {path}")
        return
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (root / path if not path.is_absolute() else path).resolve()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix() or "."
    except ValueError:
        return path.resolve().as_posix()


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _DIGEST_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _safe_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and all(
        character.isalnum() or character in "._:-" for character in value
    )


__all__ = [
    "CardEventNetDatasetFreezeError",
    "build_cardeventnet_freeze",
    "build_cardeventnet_freeze_report",
    "freeze_cardeventnet_dataset",
    "render_cardeventnet_freeze_human",
    "validate_cardeventnet_dataset_artifacts",
]
