"""Freeze and audit the interval-aware CardEventNet dataset."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .cardevent_dataset import (
    CARD_EVENTNET_COVERAGE_SCHEMA_VERSION,
    CARD_EVENTNET_DATASET_SCHEMA_VERSION,
    CARD_EVENTNET_FREEZE_RECEIPT_SCHEMA_VERSION,
    CARD_EVENTNET_SPLIT_SCHEMA_VERSION,
    CardEventNetDatasetFreezeError,
    _coverage,
    _digest,
    _validate_dataset,
)
from .cardevent_materialization import (
    CARD_EVENTNET_INTERVAL_POLICY,
    CardEventNetMaterializationResult,
)
from .source_exclusion import (
    SourceExclusionError,
    read_legacy_device_exclusion,
)

CARD_EVENTNET_INTERVAL_DATASET_REPORT_SCHEMA_VERSION = "cardeventnet-interval-dataset-report/v1"
CARD_EVENTNET_INTERVAL_SAMPLING_REPORT_SCHEMA_VERSION = "cardeventnet-interval-sampling/v1"
CARD_EVENTNET_INTERVAL_DATASET_ROOT = Path("data/operations/cardevent-datasets")
CARD_EVENTNET_INTERVAL_READINESS_REPORT = Path(
    "data/operations/cardeventnet-interval-readiness/reports/interval-readiness.json"
)
CARD_EVENTNET_INTERVAL_EXCLUSION_RECEIPT = Path(
    "data/operations/source-exclusions/legacy-device-diagnostic.json"
)
CARD_EVENTNET_SAMPLING_POLICY = {
    "version": CARD_EVENTNET_INTERVAL_POLICY,
    "anchor": "end_us",
    "interval_interior": "exclude_from_negative_evidence",
    "positive_window_s": 0.25,
    "negative_past_exclusion_s": 0.35,
    "negative_future_exclusion_s": 0.10,
    "negative_to_positive_ratio": 3,
    "confirmed_hard_negatives": "not_used",
}
_DIGEST_LENGTH = 64
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class CardEventNetIntervalDatasetError(ValueError):
    """The interval-aware CardEventNet dataset is not safe to publish."""


def freeze_cardeventnet_interval_dataset(
    repository_root: str | Path,
    *,
    operator: str,
    baseline_dataset_path: str | Path | None = None,
    interval_readiness_path: str | Path | None = None,
    exclusion_receipt_path: str | Path | None = None,
    operations_root: str | Path | None = None,
) -> dict[str, Any]:
    """Freeze a new dataset from the M6 selected revisions and filtered M3 split."""

    if _IDENTIFIER.fullmatch(operator or "") is None:
        raise CardEventNetIntervalDatasetError("operator must be a safe identifier")
    repository = Path(repository_root).expanduser().resolve()
    operations = _resolve(repository, operations_root or Path("data/operations"))
    baseline_dir, baseline, baseline_split, baseline_coverage, baseline_receipt = (
        _load_frozen_dataset(repository, baseline_dataset_path)
    )
    readiness_path = _resolve(
        repository, interval_readiness_path or CARD_EVENTNET_INTERVAL_READINESS_REPORT
    )
    readiness = _read_json(readiness_path, "M6 interval-readiness report")
    _validate_readiness(readiness)
    exclusion_path = _resolve(
        repository, exclusion_receipt_path or CARD_EVENTNET_INTERVAL_EXCLUSION_RECEIPT
    )
    try:
        exclusion, exclusion_file_sha256 = read_legacy_device_exclusion(repository, exclusion_path)
    except SourceExclusionError as error:
        raise CardEventNetIntervalDatasetError(str(error)) from error
    if exclusion is None:
        raise CardEventNetIntervalDatasetError(
            "legacy-device diagnostic-only exclusion receipt is missing"
        )
    if readiness.get("exclusion", {}).get("receipt_digest") != exclusion.get("receipt_digest"):
        raise CardEventNetIntervalDatasetError(
            "M6 interval-readiness report and exclusion receipt do not match"
        )

    base_entries = _entries_by_id(baseline)
    readiness_items = _readiness_items(readiness)
    if set(readiness_items) != set(base_entries):
        missing = sorted(set(base_entries) - set(readiness_items))
        extra = sorted(set(readiness_items) - set(base_entries))
        raise CardEventNetIntervalDatasetError(
            "M6 readiness population differs from the baseline dataset: "
            f"missing={missing}, extra={extra}"
        )
    diagnostic_ids = {
        item["recording_id"]
        for item in readiness_items.values()
        if item.get("classification") == "diagnostic_only"
    }
    receipt_ids = {
        item.get("recording_id")
        for item in exclusion.get("sources", [])
        if isinstance(item, Mapping)
    }
    if diagnostic_ids != receipt_ids:
        raise CardEventNetIntervalDatasetError(
            "M6 diagnostic-only recordings do not match the exclusion receipt"
        )
    eligible_ids = {
        recording_id
        for recording_id, item in readiness_items.items()
        if item.get("classification") == "eligible"
    }
    if len(eligible_ids) + len(diagnostic_ids) != len(base_entries):
        raise CardEventNetIntervalDatasetError("M6 readiness classifications are incomplete")

    entries: list[dict[str, Any]] = []
    for recording_id in sorted(eligible_ids):
        readiness_item = readiness_items[recording_id]
        entries.append(
            _updated_entry(
                repository,
                operations,
                base_entries[recording_id],
                readiness_item,
            )
        )

    base_partitions = _partitions(baseline_split)
    partitions = {
        partition: [
            recording_id
            for recording_id in base_partitions[partition]
            if recording_id in eligible_ids
        ]
        for partition in ("train", "validation", "test", "unassigned")
    }
    _validate_partitions(partitions, entries)
    group_partition: dict[tuple[str, str], str] = {}
    entries_by_id = _entries_by_id({"entries": entries})
    for partition in ("train", "validation", "test"):
        for recording_id in partitions[partition]:
            for raw_key in entries_by_id[recording_id].get("group_keys", []):
                if not isinstance(raw_key, list) or len(raw_key) != 2:
                    raise CardEventNetIntervalDatasetError("dataset entry group keys are invalid")
                key = (raw_key[0], raw_key[1])
                previous = group_partition.get(key)
                if previous is not None and previous != partition:
                    raise CardEventNetIntervalDatasetError(
                        f"filtered split crosses leakage group {key[0]}:{key[1]}"
                    )
                group_partition[key] = partition
    if any(not partitions[partition] for partition in ("train", "validation", "test")):
        raise CardEventNetIntervalDatasetError(
            "filtered split must keep all three partitions non-empty"
        )

    baseline_artifacts = {
        name: _sha256_file(baseline_dir / name)
        for name in ("dataset.json", "split.json", "coverage.json", "receipt.json")
    }
    readiness_file_sha256 = _sha256_file(readiness_path)
    exclusion_relative = _relative(repository, exclusion_path)
    readiness_relative = _relative(repository, readiness_path)
    dataset_core: dict[str, Any] = {
        "schema_version": CARD_EVENTNET_DATASET_SCHEMA_VERSION,
        "task": baseline.get("task", "cardevent_event_detection"),
        "readiness_digest": readiness["report_digest"],
        "split_version_id": baseline.get("split_version_id"),
        "split_version_digest": baseline.get("split_version_digest"),
        "test_sealed": True,
        "interval_aware": True,
        "target_policy": {
            "version": CARD_EVENTNET_INTERVAL_POLICY,
            "anchor": "end_us",
            "interval_interior": "exclude_from_negative_evidence",
        },
        "diagnostic_exclusion_receipt_sha256": exclusion["receipt_digest"],
        "lineage": {
            "source_dataset": {
                "path": _relative(repository, baseline_dir),
                "dataset_version_id": baseline.get("dataset_version_id"),
                "dataset_version_digest": baseline.get("dataset_version_digest"),
                "artifact_sha256": baseline_artifacts,
            },
            "interval_readiness": {
                "path": readiness_relative,
                "report_digest": readiness["report_digest"],
                "file_sha256": readiness_file_sha256,
            },
            "diagnostic_exclusion": {
                "path": exclusion_relative,
                "receipt_digest": exclusion["receipt_digest"],
                "file_sha256": exclusion_file_sha256,
                "recording_ids": sorted(diagnostic_ids),
            },
        },
        "entries": entries,
    }
    dataset_digest = _digest(dataset_core)
    dataset_id = f"cardeventnet-interval-dataset-{dataset_digest[:20]}"
    dataset = {
        **dataset_core,
        "dataset_version_id": dataset_id,
        "dataset_version_digest": dataset_digest,
    }
    split_core = {
        "schema_version": CARD_EVENTNET_SPLIT_SCHEMA_VERSION,
        "task": dataset_core["task"],
        "dataset_version_id": dataset_id,
        "dataset_version_digest": dataset_digest,
        "group_key_names": baseline_split.get(
            "group_key_names", ["game_id", "session_id", "source_lineage", "table_setup"]
        ),
        "train": partitions["train"],
        "validation": partitions["validation"],
        "test": partitions["test"],
        "unassigned": partitions["unassigned"],
        "test_sealed": True,
    }
    split_digest = _digest(split_core)
    split = {
        **split_core,
        "split_version_id": f"cardeventnet-interval-split-{split_digest[:20]}",
        "split_version_digest": split_digest,
    }
    coverage_core = {
        "schema_version": CARD_EVENTNET_COVERAGE_SCHEMA_VERSION,
        "task": dataset_core["task"],
        "dataset_version_id": dataset_id,
        "dataset_version_digest": dataset_digest,
        "partitions": _coverage(entries),
    }
    coverage = {**coverage_core, "coverage_digest": _digest(coverage_core)}
    receipt_core = {
        "schema_version": CARD_EVENTNET_FREEZE_RECEIPT_SCHEMA_VERSION,
        "receipt_type": "cardeventnet_interval_dataset_freeze",
        "operator": operator,
        "inputs": [
            {
                "kind": "baseline_dataset",
                "id": baseline.get("dataset_version_id"),
                "digest": baseline.get("dataset_version_digest"),
            },
            {
                "kind": "interval_readiness_report",
                "digest": readiness["report_digest"],
                "file_sha256": readiness_file_sha256,
            },
            {
                "kind": "diagnostic_only_source_exclusion",
                "digest": exclusion["receipt_digest"],
                "file_sha256": exclusion_file_sha256,
            },
            {
                "kind": "baseline_split",
                "id": baseline_split.get("split_version_id"),
                "digest": baseline_split.get("split_version_digest"),
            },
        ],
        "outputs": [],
    }
    receipt_digest = _digest(receipt_core)
    receipt = {
        **receipt_core,
        "outputs": [
            {"kind": "dataset", "id": dataset_id, "digest": dataset_digest},
            {"kind": "split", "id": split["split_version_id"], "digest": split_digest},
            {"kind": "coverage", "digest": coverage["coverage_digest"]},
        ],
    }
    receipt_digest = _digest(
        {key: value for key, value in receipt.items() if key != "receipt_digest"}
    )
    receipt = {
        **receipt,
        "receipt_id": f"receipt-cardeventnet-interval-freeze-{receipt_digest[:20]}",
        "receipt_digest": receipt_digest,
    }
    try:
        _validate_dataset(dataset, split, coverage, receipt, repository)
    except (CardEventNetDatasetFreezeError, ValueError) as error:
        raise CardEventNetIntervalDatasetError(
            f"interval dataset validation failed: {error}"
        ) from error

    destination_root = _resolve(repository, operations_root or Path("data/operations"))
    destination = destination_root / "cardevent-datasets" / dataset_id
    for name, payload in (
        ("dataset.json", dataset),
        ("split.json", split),
        ("coverage.json", coverage),
        ("receipt.json", receipt),
    ):
        _write_immutable(destination / name, _json_bytes(payload))
    return {
        "state": "frozen",
        "dataset_version_id": dataset_id,
        "dataset_version_digest": dataset_digest,
        "split_version_id": split["split_version_id"],
        "split_version_digest": split_digest,
        "coverage_digest": coverage["coverage_digest"],
        "receipt_id": receipt["receipt_id"],
        "receipt_digest": receipt_digest,
        "path": _relative(repository, destination),
        "partition_counts": {
            partition: len(partitions[partition]) for partition in ("train", "validation", "test")
        },
        "excluded_recordings": sorted(diagnostic_ids),
        "test_sealed": True,
        "lineage": dataset["lineage"],
        "baseline_dataset": {
            "id": baseline.get("dataset_version_id"),
            "digest": baseline.get("dataset_version_digest"),
        },
    }


def build_cardeventnet_interval_sampling_report(
    repository_root: str | Path,
    *,
    dataset_path: str | Path,
    materialized_view_path: str | Path,
    baseline_dataset_path: str | Path | None = None,
    baseline_view_path: str | Path | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """Count interval-aware labels for the materialized view and compare M3 counts."""

    repository = Path(repository_root).expanduser().resolve()
    dataset_dir, dataset, split, coverage, receipt = _load_frozen_dataset(repository, dataset_path)
    _validate_published_dataset(dataset, split, coverage, receipt, repository)
    view = _resolve(repository, materialized_view_path)
    view_manifest = _load_materialization_manifest(view, dataset)
    cache_root = _cache_root(view)
    current_entries = _entries_by_id(dataset)
    current_counts = {
        recording_id: _sampling_counts(repository, entry, cache_root, seed=seed)
        for recording_id, entry in sorted(current_entries.items())
    }
    baseline_dir, baseline, baseline_split, _, _ = _load_frozen_dataset(
        repository, baseline_dataset_path
    )
    baseline_view = (
        _resolve(repository, baseline_view_path)
        if baseline_view_path is not None
        else repository
        / ".runtime"
        / "cardevent"
        / "datasets"
        / str(baseline.get("dataset_version_id"))
    )
    baseline_manifest = _optional_materialization_manifest(baseline_view)
    baseline_cache_root = _cache_root(baseline_view)
    baseline_entries = _entries_by_id(baseline)
    baseline_counts = {
        recording_id: _sampling_counts(
            repository,
            entry,
            baseline_cache_root,
            seed=seed,
            fallback_cache_root=cache_root,
        )
        for recording_id, entry in sorted(baseline_entries.items())
    }
    changes: list[dict[str, Any]] = []
    for recording_id in sorted(baseline_entries):
        old = baseline_entries[recording_id]
        new = current_entries.get(recording_id)
        reasons: list[str] = []
        if new is None:
            reasons.append("excluded_by_legacy_device_diagnostic_receipt")
        else:
            if (
                old.get("event_revision_id") != new.get("event_revision_id")
                or old.get("event_revision_manifest_sha256")
                != new.get("event_revision_manifest_sha256")
                or old.get("event_revision_content_sha256")
                != new.get("event_revision_content_sha256")
            ):
                reasons.append("selected_maintained_reference_changed")
            if _target_counts(baseline_counts[recording_id]) != _target_counts(
                current_counts[recording_id]
            ):
                reasons.append("target_counts_changed")
            if old.get("partition") != new.get("partition"):
                reasons.append("partition_changed")
        changes.append(
            {
                "recording_id": recording_id,
                "changed": bool(reasons),
                "reasons": reasons,
                "baseline": {
                    "partition": old.get("partition"),
                    "event_revision_id": old.get("event_revision_id"),
                    "event_revision_manifest_sha256": old.get("event_revision_manifest_sha256"),
                    "event_revision_content_sha256": old.get("event_revision_content_sha256"),
                    "counts": baseline_counts[recording_id],
                },
                "current": (
                    {
                        "partition": new.get("partition"),
                        "event_revision_id": new.get("event_revision_id"),
                        "event_revision_manifest_sha256": new.get("event_revision_manifest_sha256"),
                        "event_revision_content_sha256": new.get("event_revision_content_sha256"),
                        "counts": current_counts[recording_id],
                    }
                    if new is not None
                    else None
                ),
            }
        )
    partitions = {
        partition: _sum_counts(
            [
                current_counts[recording_id]
                for recording_id in current_entries
                if current_entries[recording_id].get("partition") == partition
            ]
        )
        for partition in ("train", "validation", "test")
    }
    core: dict[str, Any] = {
        "schema_version": CARD_EVENTNET_INTERVAL_SAMPLING_REPORT_SCHEMA_VERSION,
        "dataset": {
            "path": _relative(repository, dataset_dir),
            "dataset_version_id": dataset.get("dataset_version_id"),
            "dataset_version_digest": dataset.get("dataset_version_digest"),
        },
        "materialization": {
            "path": _relative(repository, view),
            "manifest_digest": view_manifest.get("manifest_digest"),
            "file_sha256": _sha256_file(view / "materialization.json"),
        },
        "sampling_policy": {**CARD_EVENTNET_SAMPLING_POLICY, "seed": seed},
        "recordings": [
            {"recording_id": recording_id, **current_counts[recording_id]}
            for recording_id in sorted(current_counts)
        ],
        "partitions": partitions,
        "comparison": {
            "baseline_dataset": {
                "path": _relative(repository, baseline_dir),
                "dataset_version_id": baseline.get("dataset_version_id"),
                "dataset_version_digest": baseline.get("dataset_version_digest"),
                "split_version_id": baseline_split.get("split_version_id"),
                "split_version_digest": baseline_split.get("split_version_digest"),
            },
            "baseline_materialization": (
                {
                    "path": _relative(repository, baseline_view),
                    "manifest_digest": baseline_manifest.get("manifest_digest"),
                    "file_sha256": _sha256_file(baseline_view / "materialization.json"),
                }
                if baseline_manifest is not None
                else None
            ),
            "changed_recordings": [item["recording_id"] for item in changes if item["changed"]],
            "recordings": changes,
        },
    }
    core["report_digest"] = _mapping_digest(core)
    return core


def build_cardeventnet_interval_dataset_report(
    freeze_result: Mapping[str, Any],
    materialization: CardEventNetMaterializationResult,
    sampling_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Combine M7 freeze, materialization, and sampling evidence."""

    core = {
        "schema_version": CARD_EVENTNET_INTERVAL_DATASET_REPORT_SCHEMA_VERSION,
        "state": "ready",
        "dataset": {
            "id": freeze_result["dataset_version_id"],
            "digest": freeze_result["dataset_version_digest"],
            "path": freeze_result["path"],
            "test_sealed": freeze_result["test_sealed"],
            "partition_counts": freeze_result["partition_counts"],
            "excluded_recordings": freeze_result["excluded_recordings"],
        },
        "materialization": materialization.to_mapping(),
        "sampling": {
            "report_digest": sampling_report.get("report_digest"),
            "partition_counts": sampling_report.get("partitions"),
        },
        "lineage": freeze_result["lineage"],
    }
    return {**core, "report_digest": _mapping_digest(core)}


def write_cardeventnet_interval_report(
    repository_root: str | Path,
    report: Mapping[str, Any],
    path: str | Path,
) -> dict[str, Any]:
    """Write one immutable M7 JSON report."""

    repository = Path(repository_root).expanduser().resolve()
    destination = _resolve(repository, path)
    _write_immutable(destination, _json_bytes(report))
    return {
        "path": _relative(repository, destination),
        "file_sha256": _sha256_file(destination),
        "report_digest": report.get("report_digest"),
    }


def _load_frozen_dataset(
    repository: Path, dataset_path: str | Path | None
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if dataset_path is None:
        root = repository / CARD_EVENTNET_INTERVAL_DATASET_ROOT
        candidates = (
            sorted(path for path in root.glob("*/dataset.json") if path.is_file())
            if root.is_dir()
            else []
        )
        if len(candidates) != 1:
            raise CardEventNetIntervalDatasetError(
                "one explicit frozen CardEventNet dataset is required"
            )
        dataset_file = candidates[0]
    else:
        candidate = _resolve(repository, dataset_path)
        dataset_file = candidate / "dataset.json" if candidate.is_dir() else candidate
    if dataset_file.name != "dataset.json":
        raise CardEventNetIntervalDatasetError(
            "dataset path must point to dataset.json or its directory"
        )
    dataset_dir = dataset_file.parent
    dataset = _read_json(dataset_file, "CardEventNet dataset")
    split = _read_json(dataset_dir / "split.json", "CardEventNet split")
    coverage = _read_json(dataset_dir / "coverage.json", "CardEventNet coverage")
    receipt = _read_json(dataset_dir / "receipt.json", "CardEventNet freeze receipt")
    return dataset_dir, dataset, split, coverage, receipt


def _validate_published_dataset(
    dataset: Mapping[str, Any],
    split: Mapping[str, Any],
    coverage: Mapping[str, Any],
    receipt: Mapping[str, Any],
    repository: Path,
) -> None:
    try:
        _validate_dataset(dataset, split, coverage, receipt, repository)
    except (CardEventNetDatasetFreezeError, ValueError) as error:
        raise CardEventNetIntervalDatasetError(f"dataset is invalid: {error}") from error


def _validate_readiness(readiness: Mapping[str, Any]) -> None:
    digest = readiness.get("report_digest")
    core = {key: value for key, value in readiness.items() if key != "report_digest"}
    if not _valid_digest(digest) or _mapping_digest(core) != digest:
        raise CardEventNetIntervalDatasetError("M6 interval-readiness report digest is invalid")
    if readiness.get("state") != "ready":
        raise CardEventNetIntervalDatasetError("M6 interval readiness is blocked")
    if readiness.get("global_blockers") or readiness.get("blocked_recordings"):
        raise CardEventNetIntervalDatasetError("M6 interval readiness contains blockers")
    if not isinstance(readiness.get("recordings"), list):
        raise CardEventNetIntervalDatasetError("M6 interval-readiness recordings are invalid")


def _readiness_items(readiness: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in readiness["recordings"]:
        if not isinstance(item, Mapping) or not isinstance(item.get("recording_id"), str):
            raise CardEventNetIntervalDatasetError("M6 interval-readiness item is invalid")
        if item["recording_id"] in result:
            raise CardEventNetIntervalDatasetError(
                "M6 interval-readiness recording IDs are not unique"
            )
        if item.get("classification") not in {"eligible", "diagnostic_only"}:
            raise CardEventNetIntervalDatasetError(
                f"M6 interval-readiness classification is not eligible: {item['recording_id']}"
            )
        result[item["recording_id"]] = dict(item)
    return result


def _updated_entry(
    repository: Path,
    operations: Path,
    base: Mapping[str, Any],
    readiness: Mapping[str, Any],
) -> dict[str, Any]:
    recording_id = str(base["recording_id"])
    revision_id = readiness.get("selected_revision_id")
    if not isinstance(revision_id, str) or not revision_id:
        raise CardEventNetIntervalDatasetError(
            f"eligible recording has no selected revision: {recording_id}"
        )
    manifest_path, content_path = _find_revision(operations, revision_id)
    manifest_digest = _sha256_file(manifest_path)
    content_digest = _sha256_file(content_path)
    if manifest_digest != readiness.get("revision_manifest_sha256"):
        raise CardEventNetIntervalDatasetError(
            f"selected manifest digest differs for {recording_id}"
        )
    if content_digest != readiness.get("revision_content_sha256"):
        raise CardEventNetIntervalDatasetError(
            f"selected content digest differs for {recording_id}"
        )
    manifest = _read_json(manifest_path, "selected event revision manifest")
    content = _read_json(content_path, "selected event revision content")
    if manifest.get("revision_id") != revision_id or manifest.get("content_type") != "events":
        raise CardEventNetIntervalDatasetError(
            f"selected revision is not the completed event revision for {recording_id}"
        )
    source = manifest.get("source")
    source_sha256 = source.get("video_sha256") if isinstance(source, Mapping) else None
    if source_sha256 != base.get("source_sha256"):
        raise CardEventNetIntervalDatasetError(
            f"selected revision source digest differs for {recording_id}"
        )
    events = _events(content, recording_id)
    duration_us = source.get("duration_us") if isinstance(source, Mapping) else None
    if not isinstance(duration_us, int) or isinstance(duration_us, bool) or duration_us <= 0:
        raise CardEventNetIntervalDatasetError(
            f"selected revision duration is invalid for {recording_id}"
        )
    coverage = manifest.get("coverage")
    review_coverage = _review_coverage(coverage, duration_us, len(events), recording_id)
    if (
        readiness.get("reviewed_coverage_complete") is not True
        or not review_coverage["coverage_complete"]
    ):
        raise CardEventNetIntervalDatasetError(
            f"selected revision does not have complete review coverage for {recording_id}"
        )
    updated = dict(base)
    updated.update(
        {
            "event_revision_id": revision_id,
            "event_revision_manifest_path": _relative(repository, manifest_path),
            "event_revision_manifest_sha256": manifest_digest,
            "event_revision_content_path": _relative(repository, content_path),
            "event_revision_content_sha256": content_digest,
            "event_count": len(events),
            "duration_us": duration_us,
            "review_coverage": review_coverage,
        }
    )
    return updated


def _find_revision(operations: Path, revision_id: str) -> tuple[Path, Path]:
    root = operations / "pipeline" / "revisions"
    candidates = [root / revision_id / "manifest.json"]
    if not candidates[0].is_file():
        candidates = [
            path
            for path in sorted(root.rglob("manifest.json"))
            if _read_json(path, "event revision manifest").get("revision_id") == revision_id
        ]
    if len(candidates) != 1 or not candidates[0].is_file():
        raise CardEventNetIntervalDatasetError(
            f"selected event revision is unavailable: {revision_id}"
        )
    content_path = candidates[0].parent / "content.json"
    if not content_path.is_file():
        raise CardEventNetIntervalDatasetError(
            f"selected event revision content is unavailable: {revision_id}"
        )
    return candidates[0], content_path


def _events(content: Mapping[str, Any], recording_id: str) -> list[tuple[int, int]]:
    raw_events = content.get("events")
    if not isinstance(raw_events, list):
        raise CardEventNetIntervalDatasetError(
            f"selected event content has no events: {recording_id}"
        )
    result: list[tuple[int, int]] = []
    for index, item in enumerate(raw_events):
        if not isinstance(item, Mapping) or item.get("event_type") != "card_state_changed":
            raise CardEventNetIntervalDatasetError(f"event {recording_id}[{index}] is invalid")
        start, end = item.get("start_us"), item.get("end_us")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end < start
        ):
            raise CardEventNetIntervalDatasetError(
                f"event {recording_id}[{index}] interval is invalid"
            )
        result.append((start, end))
    if result != sorted(result) or len({end for _, end in result}) != len(result):
        raise CardEventNetIntervalDatasetError(f"event content is not ordered: {recording_id}")
    return result


def _review_coverage(
    coverage: Any, duration_us: int, event_count: int, recording_id: str
) -> dict[str, Any]:
    if not isinstance(coverage, Mapping) or not isinstance(coverage.get("intervals"), list):
        raise CardEventNetIntervalDatasetError(f"review coverage is missing: {recording_id}")
    intervals = coverage["intervals"]
    normalised: list[dict[str, int]] = []
    cursor = 0
    for item in intervals:
        if not isinstance(item, Mapping):
            raise CardEventNetIntervalDatasetError(f"review coverage is invalid: {recording_id}")
        start, end = item.get("start_us"), item.get("end_us")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > duration_us
            or start != cursor
        ):
            raise CardEventNetIntervalDatasetError(f"review coverage has a gap: {recording_id}")
        normalised.append({"start_us": start, "end_us": end})
        cursor = end
    complete = bool(normalised) and cursor == duration_us
    return {
        "coverage_complete": complete,
        "coverage_intervals": normalised,
        "coverage_percent": 100 if complete else (cursor * 100 / duration_us),
        "item_count": event_count,
        "reviewed_item_count": event_count,
        "annotation_event_count": event_count,
        "unresolved_uncertain_events": 0,
    }


def _sampling_counts(
    repository: Path,
    entry: Mapping[str, Any],
    cache_root: Path,
    *,
    seed: int,
    fallback_cache_root: Path | None = None,
) -> dict[str, Any]:
    recording_id = str(entry["recording_id"])
    cache = cache_root / recording_id
    if not (cache / "metadata.json").is_file() and fallback_cache_root is not None:
        cache = fallback_cache_root / recording_id
    metadata = _read_json(cache / "metadata.json", f"cache metadata for {recording_id}")
    timestamps = metadata.get("frame_timestamps_s")
    if not isinstance(timestamps, list) or not timestamps:
        raise CardEventNetIntervalDatasetError(f"cache timestamps are missing for {recording_id}")
    parsed_timestamps = [float(value) for value in timestamps]
    if any(value < 0 for value in parsed_timestamps) or parsed_timestamps != sorted(
        parsed_timestamps
    ):
        raise CardEventNetIntervalDatasetError(f"cache timestamps are invalid for {recording_id}")
    content_path = _resolve(repository, entry.get("event_revision_content_path"))
    event_intervals = _events(_read_json(content_path, "event revision content"), recording_id)
    point_targets = sum(start == end for start, end in event_intervals)
    interval_targets = sum(start < end for start, end in event_intervals)
    event_times = [end / 1_000_000 for _, end in event_intervals]
    positive = interval_ignored = other_ignored = clean_negative = 0
    for time_s in parsed_timestamps:
        is_positive = any(
            event_time - CARD_EVENTNET_SAMPLING_POLICY["positive_window_s"] <= time_s <= event_time
            for event_time in event_times
        )
        is_interval_ignored = not is_positive and any(
            start / 1_000_000 <= time_s < end / 1_000_000
            for start, end in event_intervals
            if start < end
        )
        is_clean_negative = (
            not is_positive
            and not is_interval_ignored
            and not any(
                time_s - CARD_EVENTNET_SAMPLING_POLICY["negative_past_exclusion_s"]
                <= event_time
                <= time_s + CARD_EVENTNET_SAMPLING_POLICY["negative_future_exclusion_s"]
                for event_time in event_times
            )
        )
        if is_positive:
            positive += 1
        elif is_interval_ignored:
            interval_ignored += 1
        elif is_clean_negative:
            clean_negative += 1
        else:
            other_ignored += 1
    selected_clean_negative = min(
        clean_negative,
        positive * int(CARD_EVENTNET_SAMPLING_POLICY["negative_to_positive_ratio"]),
    )
    return {
        "partition": entry.get("partition"),
        "point_targets": point_targets,
        "interval_targets": interval_targets,
        "event_targets": len(event_intervals),
        "positive_samples": positive,
        "ignored_interval_samples": interval_ignored,
        "other_ignored_samples": other_ignored,
        "eligible_clean_negatives": clean_negative,
        "selected_positive_samples": positive,
        "selected_clean_negatives": selected_clean_negative,
        "selected_samples": positive + selected_clean_negative,
        "available_decision_times": len(parsed_timestamps),
        "cache_metadata_sha256": _sha256_file(cache / "metadata.json"),
        "sampling_seed": seed,
    }


def _target_counts(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "point_targets",
            "interval_targets",
            "positive_samples",
            "ignored_interval_samples",
            "other_ignored_samples",
            "eligible_clean_negatives",
        )
    }


def _sum_counts(values: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    keys = (
        "point_targets",
        "interval_targets",
        "event_targets",
        "positive_samples",
        "ignored_interval_samples",
        "other_ignored_samples",
        "eligible_clean_negatives",
        "selected_positive_samples",
        "selected_clean_negatives",
        "selected_samples",
        "available_decision_times",
    )
    return {key: sum(int(value.get(key, 0)) for value in values) for key in keys}


def _validate_partitions(
    partitions: Mapping[str, Sequence[str]], entries: Sequence[Mapping[str, Any]]
) -> None:
    entry_ids = {entry.get("recording_id") for entry in entries}
    assigned: set[str] = set()
    for partition in ("train", "validation", "test", "unassigned"):
        for recording_id in partitions[partition]:
            if recording_id in assigned or recording_id not in entry_ids:
                raise CardEventNetIntervalDatasetError("filtered split and entries disagree")
            assigned.add(recording_id)
    if assigned != entry_ids:
        raise CardEventNetIntervalDatasetError(
            "filtered split does not assign every eligible recording"
        )


def _partitions(split: Mapping[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for partition in ("train", "validation", "test", "unassigned"):
        values = split.get(partition, [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise CardEventNetIntervalDatasetError("baseline split partitions are invalid")
        result[partition] = list(values)
    return result


def _entries_by_id(dataset: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    entries = dataset.get("entries")
    if not isinstance(entries, list):
        raise CardEventNetIntervalDatasetError("dataset entries are invalid")
    result: dict[str, dict[str, Any]] = {}
    for item in entries:
        if not isinstance(item, Mapping) or not isinstance(item.get("recording_id"), str):
            raise CardEventNetIntervalDatasetError("dataset entry is invalid")
        if item["recording_id"] in result:
            raise CardEventNetIntervalDatasetError("dataset recording IDs are not unique")
        result[item["recording_id"]] = dict(item)
    return result


def _load_materialization_manifest(view: Path, dataset: Mapping[str, Any]) -> dict[str, Any]:
    manifest = _optional_materialization_manifest(view)
    if manifest is None:
        raise CardEventNetIntervalDatasetError(f"materialization manifest is missing: {view}")
    digest = manifest.get("manifest_digest")
    core = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    if not _valid_digest(digest) or _mapping_digest(core) != digest:
        raise CardEventNetIntervalDatasetError("materialization manifest digest is invalid")
    if manifest.get("dataset", {}).get("id") != dataset.get("dataset_version_id"):
        raise CardEventNetIntervalDatasetError("materialization uses the wrong dataset")
    policy = manifest.get("event_target_policy")
    if policy != {
        "version": CARD_EVENTNET_INTERVAL_POLICY,
        "anchor": "end_us",
        "interval_interior": "exclude_from_negative_evidence",
    }:
        raise CardEventNetIntervalDatasetError("materialization does not use stable-end-anchor-v1")
    return manifest


def _optional_materialization_manifest(view: Path) -> dict[str, Any] | None:
    path = view / "materialization.json"
    return _read_json(path, "materialization manifest") if path.is_file() else None


def _cache_root(view: Path) -> Path:
    root = view / "cache"
    if not root.is_dir():
        raise CardEventNetIntervalDatasetError(f"materialized cache directory is missing: {root}")
    return root


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventNetIntervalDatasetError(f"could not read {field}: {path}") from error
    if not isinstance(value, Mapping):
        raise CardEventNetIntervalDatasetError(f"{field} must be a JSON object: {path}")
    return dict(value)


def _resolve(repository: Path, value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    return (repository / candidate if not candidate.is_absolute() else candidate).resolve()


def _relative(repository: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repository).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise CardEventNetIntervalDatasetError(f"immutable artifact differs: {path}")
        return
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise CardEventNetIntervalDatasetError(f"could not hash {path}") from error
    return digest.hexdigest()


def _mapping_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _DIGEST_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "CARD_EVENTNET_INTERVAL_DATASET_REPORT_SCHEMA_VERSION",
    "CARD_EVENTNET_INTERVAL_DATASET_ROOT",
    "CARD_EVENTNET_INTERVAL_READINESS_REPORT",
    "CARD_EVENTNET_INTERVAL_SAMPLING_REPORT_SCHEMA_VERSION",
    "CARD_EVENTNET_INTERVAL_EXCLUSION_RECEIPT",
    "CardEventNetIntervalDatasetError",
    "build_cardeventnet_interval_dataset_report",
    "build_cardeventnet_interval_sampling_report",
    "freeze_cardeventnet_interval_dataset",
    "write_cardeventnet_interval_report",
]
