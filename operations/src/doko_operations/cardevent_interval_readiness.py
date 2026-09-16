"""Audit CardEventNet interval review state and publish diagnostic-only exclusions."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .source_exclusion import (
    LEGACY_DEVICE_DIAGNOSTIC_ROLE,
    LEGACY_DEVICE_EXCLUSION_REASON,
    LEGACY_DEVICE_EXCLUSION_RECEIPT_SCHEMA_VERSION,
    LEGACY_DEVICE_RECORDING_ID_SET,
    LEGACY_DEVICE_RECORDING_IDS,
    LEGACY_DEVICE_SOURCE_ASSET_ID_SET,
    LEGACY_DEVICE_SOURCE_DIGESTS,
    SourceExclusionError,
    exclusion_path,
    read_legacy_device_exclusion,
    validate_legacy_device_exclusion,
)

CARD_EVENTNET_INTERVAL_READINESS_SCHEMA_VERSION = "cardeventnet-interval-readiness/v1"
CARD_EVENTNET_ZERO_INTERVAL_ATTESTATION_SCHEMA_VERSION = "cardeventnet-zero-interval-attestation/v1"
CARD_EVENTNET_INTERVAL_READINESS_ROOT = Path("data/operations/cardeventnet-interval-readiness")
_PARTITIONS = frozenset({"train", "validation", "test"})
_DIGEST_LENGTH = 64


class CardEventNetIntervalReadinessError(ValueError):
    """The interval-readiness report or an M6 receipt is invalid."""


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise CardEventNetIntervalReadinessError(f"could not read {path}") from error
    return digest.hexdigest()


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventNetIntervalReadinessError(f"could not read {field}: {path}") from error
    if not isinstance(value, Mapping):
        raise CardEventNetIntervalReadinessError(f"{field} must be a JSON object: {path}")
    return dict(value)


def _resolve(repository: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (repository / path if not path.is_absolute() else path).resolve()


def _relative(repository: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repository).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _safe_identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and all(character.isalnum() or character in "._:-" for character in value)
    )


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise CardEventNetIntervalReadinessError(f"immutable artifact differs: {path}")
        return
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_dataset(repository: Path, dataset_path: str | Path | None) -> tuple[Path, dict[str, Any]]:
    if dataset_path is None:
        root = repository / "data" / "operations" / "cardevent-datasets"
        candidates = (
            sorted(
                path / "dataset.json"
                for path in root.iterdir()
                if path.is_dir() and (path / "dataset.json").is_file()
            )
            if root.is_dir()
            else []
        )
        if len(candidates) != 1:
            raise CardEventNetIntervalReadinessError(
                "interval readiness needs one explicit frozen CardEventNet dataset; pass --dataset"
            )
        dataset_file = candidates[0]
    else:
        candidate = _resolve(repository, dataset_path)
        dataset_file = candidate / "dataset.json" if candidate.is_dir() else candidate
    dataset = _read_json(dataset_file, "CardEventNet dataset")
    if not isinstance(dataset.get("entries"), list) or not dataset["entries"]:
        raise CardEventNetIntervalReadinessError("CardEventNet dataset has no entries")
    return dataset_file.parent, dataset


def _load_revision(
    repository: Path, operations: Path, revision_id: str | None
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
    Path | None,
    Path | None,
    str | None,
    str | None,
]:
    if not isinstance(revision_id, str) or not revision_id:
        return None, None, None, None, None, None
    root = operations / "pipeline" / "revisions"
    candidates = sorted(root.glob(f"{revision_id}/manifest.json"))
    if not candidates:
        candidates = sorted(root.rglob("manifest.json"))
        candidates = [
            path
            for path in candidates
            if _read_json(path, "event revision manifest").get("revision_id") == revision_id
        ]
    if len(candidates) != 1:
        return None, None, None, None, None, None
    manifest_path = candidates[0]
    content_path = manifest_path.parent / "content.json"
    manifest = _read_json(manifest_path, "event revision manifest")
    content = _read_json(content_path, "event revision content")
    return (
        manifest,
        content,
        manifest_path,
        content_path,
        _file_digest(manifest_path),
        _file_digest(content_path),
    )


def _coverage_duration(manifest: Mapping[str, Any]) -> tuple[int, bool]:
    source = manifest.get("source")
    duration = source.get("duration_us") if isinstance(source, Mapping) else None
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
        return 0, False
    coverage = manifest.get("coverage")
    raw_intervals = coverage.get("intervals") if isinstance(coverage, Mapping) else None
    if not isinstance(raw_intervals, list):
        return 0, False
    intervals: list[tuple[int, int]] = []
    for item in raw_intervals:
        if not isinstance(item, Mapping):
            return 0, False
        start, end = item.get("start_us"), item.get("end_us")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or start > end
            or end > duration
        ):
            return 0, False
        intervals.append((start, end))
    intervals.sort()
    cursor = 0
    covered = 0
    for start, end in intervals:
        if start > cursor:
            return covered, False
        if end > cursor:
            covered += end - max(start, cursor)
            cursor = end
    return covered, cursor == duration


def _event_counts(content: Mapping[str, Any]) -> tuple[int, int, int]:
    raw_events = content.get("events")
    if not isinstance(raw_events, list):
        return 0, 0, 0
    points = intervals = 0
    for event in raw_events:
        if not isinstance(event, Mapping):
            continue
        start, end = event.get("start_us"), event.get("end_us")
        if isinstance(start, int) and isinstance(end, int):
            if start == end:
                points += 1
            elif start < end:
                intervals += 1
    return points, intervals, len(raw_events)


def _attestation_path(operations: Path, recording_id: str) -> Path:
    return (
        operations
        / "cardeventnet-interval-readiness"
        / "zero-interval-decisions"
        / f"{recording_id}.json"
    )


def _valid_attestation(
    path: Path,
    *,
    recording_id: str,
    revision_id: str,
    manifest_sha256: str,
    content_sha256: str,
    source_sha256: str | None,
) -> bool:
    if not path.is_file():
        return False
    try:
        value = _read_json(path, "zero-interval attestation")
    except CardEventNetIntervalReadinessError:
        return False
    return (
        value.get("schema_version") == CARD_EVENTNET_ZERO_INTERVAL_ATTESTATION_SCHEMA_VERSION
        and value.get("recording_id") == recording_id
        and value.get("decision") == "no_card_state_change_interval"
        and value.get("selected_revision_id") == revision_id
        and value.get("revision_manifest_sha256") == manifest_sha256
        and value.get("revision_content_sha256") == content_sha256
        and value.get("source_sha256") == source_sha256
        and _digest({key: value[key] for key in value if key != "attestation_digest"})
        == value.get("attestation_digest")
    )


def _dataset_entries(dataset: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries = dataset.get("entries")
    if not isinstance(entries, list):
        raise CardEventNetIntervalReadinessError("CardEventNet dataset entries are invalid")
    result = [dict(item) for item in entries if isinstance(item, Mapping)]
    if len(result) != len(entries):
        raise CardEventNetIntervalReadinessError("CardEventNet dataset contains an invalid entry")
    ids = [item.get("recording_id") for item in result]
    if any(not isinstance(item, str) for item in ids) or len(set(ids)) != len(ids):
        raise CardEventNetIntervalReadinessError(
            "CardEventNet dataset recording IDs are not unique"
        )
    return sorted(result, key=lambda item: item["recording_id"])


def build_cardeventnet_interval_readiness(
    repository_root: str | Path,
    *,
    dataset_path: str | Path | None = None,
    operations_root: str | Path | None = None,
    exclusion_receipt_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build the deterministic M6 interval-readiness report."""

    repository = Path(repository_root).expanduser().resolve()
    operations = _resolve(repository, operations_root or Path("data/operations"))
    dataset_dir, dataset = _load_dataset(repository, dataset_path)
    try:
        exclusion, exclusion_file_digest = read_legacy_device_exclusion(
            repository, exclusion_receipt_path
        )
    except SourceExclusionError as error:
        raise CardEventNetIntervalReadinessError(str(error)) from error

    global_blockers: list[str] = []
    if exclusion is None:
        global_blockers.append(
            "legacy-device diagnostic-only exclusion receipt is missing; publish the M6 receipt"
        )
    entries = _dataset_entries(dataset)
    items: list[dict[str, Any]] = []
    for entry in entries:
        recording_id = entry["recording_id"]
        partition = entry.get("partition")
        blockers: list[str] = []
        if partition not in _PARTITIONS:
            blockers.append("dataset partition is missing or invalid")
            partition = None
        reference_root = operations / "pipeline-references" / recording_id / "events"
        state = (
            _read_json(reference_root / "state.json", "maintained event reference state")
            if (reference_root / "state.json").is_file()
            else {}
        )
        reference_state = state.get("draft_state", "missing")
        selected_revision_id = state.get("selected_completed_revision_id") or state.get(
            "source_revision_id"
        )
        (
            manifest,
            content,
            manifest_path,
            content_path,
            manifest_digest,
            content_digest,
        ) = _load_revision(repository, operations, selected_revision_id)
        points = intervals = event_count = 0
        reviewed_duration_us = 0
        coverage_complete = False
        content_type = entry.get("content_type")
        source_sha256 = entry.get("source_sha256")
        if manifest is None or content is None or manifest_path is None or content_path is None:
            blockers.append("selected event revision is missing")
        else:
            content_type = manifest.get("content_type", content_type)
            if content_type != "events":
                blockers.append("selected revision is not event data")
            points, intervals, event_count = _event_counts(content)
            reviewed_duration_us, coverage_complete = _coverage_duration(manifest)
            source = manifest.get("source")
            if isinstance(source, Mapping):
                source_sha256 = source.get("video_sha256", source_sha256)
            if entry.get("source_sha256") not in {None, source_sha256}:
                blockers.append("selected revision source digest differs from dataset")
            if entry.get("event_revision_id") not in {None, selected_revision_id}:
                # The M6 interval pass can replace the selected maintained revision.  The
                # immutable M3 dataset remains the population and partition authority.
                pass
            if not coverage_complete:
                blockers.append("selected revision does not cover the full recording")
            if manifest_digest is not None and content_digest is not None:
                expected_manifest = entry.get("event_revision_manifest_sha256")
                if expected_manifest and selected_revision_id == entry.get("event_revision_id"):
                    # A changed maintained reference is expected in M6.  The report binds the
                    # current selected revision instead of silently using the frozen M3 bytes.
                    pass
        is_diagnostic = (
            recording_id in LEGACY_DEVICE_RECORDING_ID_SET
            or entry.get("source_asset_id") in LEGACY_DEVICE_SOURCE_ASSET_ID_SET
        )
        if is_diagnostic:
            classification = "diagnostic_only"
            blockers = []
            decision = "legacy_device_diagnostic"
            action = None
        else:
            if reference_state != "completed":
                blockers.append(f"maintained event reference is {reference_state}, not completed")
            if (
                manifest is not None
                and intervals == 0
                and selected_revision_id
                and manifest_digest
                and content_digest
            ):
                attested = _valid_attestation(
                    _attestation_path(operations, recording_id),
                    recording_id=recording_id,
                    revision_id=selected_revision_id,
                    manifest_sha256=manifest_digest,
                    content_sha256=content_digest,
                    source_sha256=source_sha256,
                )
            else:
                attested = False
            if intervals > 0:
                decision = "interval_reviewed"
            elif attested:
                decision = "attested_no_interval"
            else:
                decision = "interval_decision_required"
                blockers.append(
                    "zero interval count needs another interval review or an explicit "
                    "no-interval attestation"
                )
            if not blockers:
                classification = "eligible"
                action = None
            else:
                classification = "blocked"
                action = {
                    "recording_id": recording_id,
                    "partition": partition,
                    "command": (
                        f"review {recording_id} in the recording workspace and publish the "
                        "maintained "
                        "interval reference, or attest no card-state change interval with "
                        "doko data cardevent interval-readiness "
                        f"--attest-no-interval {recording_id}"
                    ),
                }
        items.append(
            {
                "recording_id": recording_id,
                "partition": partition,
                "content_type": content_type,
                "reference_state": reference_state,
                "selected_revision_id": selected_revision_id,
                "revision_manifest_sha256": manifest_digest,
                "revision_content_sha256": content_digest,
                "point_count": points,
                "interval_count": intervals,
                "event_count": event_count,
                "reviewed_duration_us": reviewed_duration_us,
                "reviewed_coverage_complete": coverage_complete,
                "decision": decision,
                "classification": classification,
                "blockers": sorted(set(blockers)),
                "operator_action": action,
            }
        )
    eligible = [item["recording_id"] for item in items if item["classification"] == "eligible"]
    diagnostic = [
        item["recording_id"] for item in items if item["classification"] == "diagnostic_only"
    ]
    blocked = [item["recording_id"] for item in items if item["classification"] == "blocked"]
    core: dict[str, Any] = {
        "schema_version": CARD_EVENTNET_INTERVAL_READINESS_SCHEMA_VERSION,
        "state": "ready" if not global_blockers and not blocked else "blocked",
        "dataset": {
            "path": _relative(repository, dataset_dir),
            "dataset_version_id": dataset.get("dataset_version_id"),
            "dataset_version_digest": dataset.get("dataset_version_digest"),
            "recording_count": len(entries),
        },
        "exclusion": {
            "path": _relative(repository, exclusion_path(repository, exclusion_receipt_path)),
            "receipt_digest": exclusion.get("receipt_digest") if exclusion else None,
            "file_sha256": exclusion_file_digest,
            "role": LEGACY_DEVICE_DIAGNOSTIC_ROLE,
            "recording_ids": sorted(LEGACY_DEVICE_RECORDING_IDS),
        },
        "counts": {
            "historical_recordings": len(items),
            "eligible": len(eligible),
            "diagnostic_only": len(diagnostic),
            "blocked": len(blocked),
            "point_events": sum(item["point_count"] for item in items),
            "interval_events": sum(item["interval_count"] for item in items),
        },
        "eligible_recordings": eligible,
        "diagnostic_only_recordings": diagnostic,
        "blocked_recordings": blocked,
        "global_blockers": sorted(global_blockers),
        "recordings": items,
        "next_action": (
            "retain this report and continue with the interval-aware dataset freeze."
            if not global_blockers and not blocked
            else "complete each listed review or attestation, then rerun interval-readiness."
        ),
    }
    core["report_digest"] = _digest(core)
    return core


def write_cardeventnet_zero_interval_attestation(
    repository_root: str | Path,
    recording_id: str,
    *,
    operator: str,
    dataset_path: str | Path | None = None,
    operations_root: str | Path | None = None,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    """Bind an explicit no-interval decision to the selected revision digests."""

    if not _safe_identifier(recording_id) or not _safe_identifier(operator):
        raise CardEventNetIntervalReadinessError(
            "recording_id and operator must be safe identifiers"
        )
    repository = Path(repository_root).expanduser().resolve()
    operations = _resolve(repository, operations_root or Path("data/operations"))
    _, dataset = _load_dataset(repository, dataset_path)
    entry = next(
        (item for item in _dataset_entries(dataset) if item["recording_id"] == recording_id), None
    )
    if entry is None:
        raise CardEventNetIntervalReadinessError(
            f"recording is not in the frozen dataset: {recording_id}"
        )
    if (
        recording_id in LEGACY_DEVICE_RECORDING_ID_SET
        or entry.get("source_asset_id") in LEGACY_DEVICE_SOURCE_ASSET_ID_SET
    ):
        raise CardEventNetIntervalReadinessError(
            "diagnostic-only recordings do not need interval attestations"
        )
    reference_root = operations / "pipeline-references" / recording_id / "events"
    state = _read_json(reference_root / "state.json", "maintained event reference state")
    if state.get("draft_state") != "completed":
        raise CardEventNetIntervalReadinessError(
            "zero-interval attestation requires a completed reference"
        )
    revision_id = state.get("selected_completed_revision_id") or state.get("source_revision_id")
    manifest, content, _, _, manifest_digest, content_digest = _load_revision(
        repository, operations, revision_id
    )
    if manifest is None or content is None or manifest_digest is None or content_digest is None:
        raise CardEventNetIntervalReadinessError("selected event revision is unavailable")
    _, intervals, _ = _event_counts(content)
    if intervals != 0:
        raise CardEventNetIntervalReadinessError(
            "recording has interval events; do not attest no interval"
        )
    source = manifest.get("source")
    source_sha256 = source.get("video_sha256") if isinstance(source, Mapping) else None
    core: dict[str, Any] = {
        "schema_version": CARD_EVENTNET_ZERO_INTERVAL_ATTESTATION_SCHEMA_VERSION,
        "recording_id": recording_id,
        "partition": entry.get("partition"),
        "decision": "no_card_state_change_interval",
        "operator": operator,
        "selected_revision_id": revision_id,
        "revision_manifest_sha256": manifest_digest,
        "revision_content_sha256": content_digest,
        "source_sha256": source_sha256,
        "created_at_utc": created_at_utc
        or datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    attestation = {**core, "attestation_digest": _digest(core)}
    path = _attestation_path(operations, recording_id)
    _write_immutable(path, _json_bytes(attestation))
    return {"path": _relative(repository, path), **attestation}


def write_legacy_device_exclusion_receipt(
    repository_root: str | Path,
    *,
    operator: str,
    dataset_path: str | Path | None = None,
    output_path: str | Path | None = None,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    """Publish the immutable five-recording legacy-device diagnostic receipt."""

    if not _safe_identifier(operator):
        raise CardEventNetIntervalReadinessError("operator must be a safe identifier")
    repository = Path(repository_root).expanduser().resolve()
    destination = exclusion_path(repository, output_path)
    if destination.is_file():
        try:
            receipt = _read_json(destination, "legacy-device exclusion receipt")
            validate_legacy_device_exclusion(receipt)
        except SourceExclusionError as error:
            raise CardEventNetIntervalReadinessError(str(error)) from error
        return {"path": _relative(repository, destination), **receipt}

    _, dataset = _load_dataset(repository, dataset_path)
    entries = {item["recording_id"]: item for item in _dataset_entries(dataset)}
    sources: list[dict[str, Any]] = []
    for recording_id in sorted(LEGACY_DEVICE_RECORDING_ID_SET):
        entry = entries.get(recording_id)
        if entry is None:
            raise CardEventNetIntervalReadinessError(
                f"diagnostic recording is absent from dataset: {recording_id}"
            )
        source_path = _resolve(repository, entry.get("source_path"))
        source_record_path = source_path.parent.parent / "source-record.json"
        source_record = _read_json(source_record_path, "source record")
        source_asset_id = source_record.get("source_asset_id")
        source_sha256 = source_record.get("sha256")
        if source_asset_id not in LEGACY_DEVICE_SOURCE_ASSET_ID_SET:
            raise CardEventNetIntervalReadinessError(
                f"source asset is not in the M6 set: {recording_id}"
            )
        if source_sha256 != LEGACY_DEVICE_SOURCE_DIGESTS[source_asset_id]:
            raise CardEventNetIntervalReadinessError(f"source digest differs for {recording_id}")
        sources.append(
            {
                "recording_id": recording_id,
                "source_asset_id": source_asset_id,
                "source_sha256": source_sha256,
                "role": LEGACY_DEVICE_DIAGNOSTIC_ROLE,
            }
        )
    core: dict[str, Any] = {
        "schema_version": LEGACY_DEVICE_EXCLUSION_RECEIPT_SCHEMA_VERSION,
        "receipt_type": LEGACY_DEVICE_DIAGNOSTIC_ROLE,
        "role": LEGACY_DEVICE_DIAGNOSTIC_ROLE,
        "operator": operator,
        "reason": LEGACY_DEVICE_EXCLUSION_REASON,
        "decision": "exclude_from_future_datasets_and_promotion_gates",
        "sources": sources,
        "created_at_utc": created_at_utc
        or datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "dataset_population": dataset.get("dataset_version_id"),
    }
    receipt = {**core, "receipt_digest": _digest(core)}
    _write_immutable(destination, _json_bytes(receipt))
    return {"path": _relative(repository, destination), **receipt}


def write_cardeventnet_interval_readiness_report(
    repository_root: str | Path,
    report: Mapping[str, Any],
    path: str | Path,
) -> dict[str, Any]:
    """Retain one immutable JSON copy of a deterministic interval-readiness report."""

    repository = Path(repository_root).expanduser().resolve()
    destination = _resolve(repository, path)
    _write_immutable(destination, _json_bytes(report))
    return {
        "path": _relative(repository, destination),
        "report_digest": report.get("report_digest"),
    }


def render_cardeventnet_interval_readiness_human(report: Mapping[str, Any]) -> str:
    """Render the interval-readiness report for an operator."""

    counts = report["counts"]
    lines = [
        "CardEventNet interval readiness",
        f"state: {report['state']}",
        f"historical recordings: {counts['historical_recordings']}",
        f"eligible: {counts['eligible']}",
        f"diagnostic-only: {counts['diagnostic_only']}",
        f"blocked: {counts['blocked']}",
        f"events: points={counts['point_events']}, intervals={counts['interval_events']}",
    ]
    for blocker in report.get("global_blockers", []):
        lines.append(f"blocker: {blocker}")
    for item in report["recordings"]:
        if item["classification"] == "blocked":
            lines.append(
                f"  - {item['recording_id']} | {item['partition']} | " + "; ".join(item["blockers"])
            )
    lines.append(f"report digest: {report['report_digest']}")
    return "\n".join(lines) + "\n"


__all__ = [
    "CARD_EVENTNET_INTERVAL_READINESS_ROOT",
    "CARD_EVENTNET_INTERVAL_READINESS_SCHEMA_VERSION",
    "CARD_EVENTNET_ZERO_INTERVAL_ATTESTATION_SCHEMA_VERSION",
    "CardEventNetIntervalReadinessError",
    "build_cardeventnet_interval_readiness",
    "render_cardeventnet_interval_readiness_human",
    "write_cardeventnet_interval_readiness_report",
    "write_cardeventnet_zero_interval_attestation",
    "write_legacy_device_exclusion_receipt",
]
