"""Read-only human-review readiness for the current CardEventNet corpus."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from .intake import BundleInspection, inspect_repository

CARD_EVENTNET_READINESS_SCHEMA_VERSION = "cardeventnet-readiness/v1"
CARD_EVENTNET_READINESS_RECEIPT_SCHEMA_VERSION = "cardeventnet-readiness-receipt/v1"
CARD_EVENTNET_TASK = "cardevent_event_detection"
PRIMARY_STATES = (
    "source_missing",
    "metadata_or_permission_missing",
    "annotation_missing",
    "annotation_imported_review_required",
    "review_in_progress",
    "review_complete",
    "excluded",
)
REVIEWED_ITEM_STATES = frozenset(
    {
        "accepted",
        "rejected",
        "added",
        "corrected",
        "empty",
        "unusable",
        "identity_unusable",
        "source_problem",
    }
)
GROUP_FIELDS = ("session_id", "table_setup", "source_lineage")
PARTITIONS = ("train", "validation", "test")


class CardEventNetReadinessError(ValueError):
    """The readiness report could not be built or its receipt could not be written."""


@dataclass(frozen=True, slots=True)
class CardEventNetReadiness:
    """The complete deterministic CardEventNet human-review report."""

    repository_root: str
    intake_root: str
    operations_root: str
    migration: dict[str, Any]
    recordings: tuple[dict[str, Any], ...]
    review_queue: tuple[dict[str, Any], ...]

    def to_mapping(self) -> dict[str, Any]:
        primary_states = Counter(item["primary_state"] for item in self.recordings)
        blocker_counts = Counter(
            blocker for item in self.recordings for blocker in item.get("blockers", ())
        )
        eligible = [
            item["recording_id"]
            for item in self.recordings
            if item.get("eligible_partitions")
        ]
        excluded = [
            {
                "recording_id": item["recording_id"],
                "reason": item.get("reason"),
            }
            for item in self.recordings
            if item["primary_state"] == "excluded"
        ]
        core: dict[str, Any] = {
            "schema_version": CARD_EVENTNET_READINESS_SCHEMA_VERSION,
            "read_only": True,
            "repository_root": self.repository_root,
            "intake_root": self.intake_root,
            "operations_root": self.operations_root,
            "state": "ready" if not self.review_queue and not blocker_counts else "blocked",
            "migration": self.migration,
            "counts": {
                "recordings": len(self.recordings),
                "review_queue": len(self.review_queue),
                "eligible_recordings": len(eligible),
                "excluded_recordings": len(excluded),
                "primary_states": {
                    state: primary_states.get(state, 0) for state in PRIMARY_STATES
                },
                "blockers": dict(sorted(blocker_counts.items())),
            },
            "eligible_recordings": eligible,
            "excluded_recordings": excluded,
            "recordings": list(self.recordings),
            "review_queue": list(self.review_queue),
        }
        core["report_digest"] = _digest(core)
        return core


def build_cardeventnet_readiness(
    repository_root: str | Path,
    *,
    intake_root: str | Path | None = None,
    operations_root: str | Path | None = None,
) -> CardEventNetReadiness:
    """Build one deterministic report from shared intake and operations artifacts."""

    repository = Path(repository_root).expanduser().resolve()
    if not repository.is_dir():
        raise CardEventNetReadinessError(f"repository root is not a directory: {repository}")
    intake = _resolve(repository, intake_root or Path("data/intake/recordings"))
    operations = _resolve(repository, operations_root or Path("data/operations"))
    inspections = _bundle_inspections(repository, intake, operations)
    revisions = _event_revisions(repository, operations)
    split = _active_split(repository, operations)
    migration = _migration_facts(repository, intake, operations)
    references = _reference_ids(operations)

    selected: dict[str, tuple[BundleInspection | None, Path | None, dict[str, Any]]] = {}
    for inspection in inspections:
        task = next(
            (
                task
                for task in inspection.tasks
                if task.task == CARD_EVENTNET_TASK and task.disposition == "selected"
            ),
            None,
        )
        if task is None or inspection.recording_id is None:
            continue
        bundle_path = repository / PurePosixPath(inspection.path)
        selected[inspection.recording_id] = (
            inspection,
            bundle_path,
            _read_object(bundle_path / "source-record.json") or {},
        )

    for item in migration.get("items", ()):
        recording_id = item.get("recording_id")
        if not isinstance(recording_id, str) or recording_id in selected:
            continue
        selected[recording_id] = (None, None, {})
    for recording_id in references:
        if recording_id not in selected:
            selected[recording_id] = (None, None, {})

    records = tuple(
        _readiness_record(
            repository,
            operations,
            recording_id,
            inspection,
            bundle_path,
            source,
            revisions.get(recording_id, ()),
            split,
            migration,
        )
        for recording_id, (inspection, bundle_path, source) in sorted(selected.items())
    )
    queue = tuple(
        {
            "recording_id": item["recording_id"],
            "source_video": item["source_video"],
            "reason": item["reason"],
            "review_progress": item["review_progress"],
            "workspace_route": item["action"]["workspace_route"],
            "command": item["action"]["command"],
        }
        for item in records
        if item.get("action") is not None
    )
    return CardEventNetReadiness(
        repository_root=".",
        intake_root=_relative(intake, repository),
        operations_root=_relative(operations, repository),
        migration={key: value for key, value in migration.items() if key != "items"},
        recordings=records,
        review_queue=queue,
    )


def render_cardeventnet_readiness_json(report: CardEventNetReadiness) -> str:
    """Render the canonical machine-readable readiness report."""

    return json.dumps(report.to_mapping(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_cardeventnet_readiness_human(
    report: CardEventNetReadiness, *, receipt_path: str | None = None
) -> str:
    """Render the operator queue without requiring JSON inspection."""

    data = report.to_mapping()
    counts = data["counts"]
    lines = [
        "CardEventNet human annotation readiness",
        f"state: {data['state']}",
        f"recordings: {counts['recordings']}",
        f"review queue: {counts['review_queue']}",
        f"eligible recordings: {counts['eligible_recordings']}",
        "primary states: "
        + ", ".join(
            f"{state}={count}" for state, count in counts["primary_states"].items() if count
        ),
        "migration gaps: "
        + (", ".join(data["migration"]["not_migrated"]) or "none reported"),
    ]
    if counts["blockers"]:
        lines.append("secondary blockers:")
        lines.extend(f"  - {name}: {count}" for name, count in counts["blockers"].items())
    if data["review_queue"]:
        lines.append("human action queue:")
        for item in data["review_queue"]:
            progress = item["review_progress"]
            lines.append(
                f"  - {item['recording_id']} | {item['source_video']} | {item['reason']} | "
                f"{progress['reviewed_item_count']}/{progress['item_count']} items, "
                f"{progress['coverage_percent']}% recording coverage | "
                f"open {item['workspace_route']}"
            )
    else:
        lines.append("human action queue: empty")
    lines.append(
        "next action: "
        + (
            "open each queued recording in the recording workspace and complete "
            "full-recording coverage."
            if data["review_queue"]
            else "review is complete; retain this report and continue with the dataset freeze."
        )
    )
    if receipt_path is not None:
        lines.append(f"readiness receipt: {receipt_path}")
    return "\n".join(lines) + "\n"


def write_cardeventnet_readiness_receipt(
    report: CardEventNetReadiness,
    path: str | Path,
    *,
    operator: str,
) -> dict[str, Any]:
    """Write a digest-backed readiness receipt after explicit operator action."""

    if not _safe_identifier(operator):
        raise CardEventNetReadinessError("operator must be a safe non-empty identifier")
    destination = Path(path).expanduser().resolve()
    report_data = report.to_mapping()
    core: dict[str, Any] = {
        "schema_version": CARD_EVENTNET_READINESS_RECEIPT_SCHEMA_VERSION,
        "receipt_type": "cardevent_human_annotation_readiness",
        "operator": operator,
        "created_at_utc": _now(),
        "state": report_data["state"],
        "report_digest": report_data["report_digest"],
        "counts": report_data["counts"],
        "excluded_recordings": report_data["excluded_recordings"],
        "incomplete_recordings": [
            item["recording_id"]
            for item in report_data["recordings"]
            if item["primary_state"] not in {"review_complete", "excluded"}
        ],
    }
    receipt = {**core, "receipt_sha256": _digest(core)}
    _atomic_write_json(destination, receipt)
    return {"path": _relative(destination, report_data["repository_root"]), **receipt}


def _readiness_record(
    repository: Path,
    operations: Path,
    recording_id: str,
    inspection: BundleInspection | None,
    bundle_path: Path | None,
    source: Mapping[str, Any],
    revisions: Sequence[dict[str, Any]],
    split: Mapping[str, Any],
    migration: Mapping[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    source = dict(source)
    manifest = _read_object(bundle_path / "manifest.json") if bundle_path is not None else None
    migration_item = next(
        (
            item
            for item in migration.get("items", ())
            if isinstance(item, Mapping) and item.get("recording_id") == recording_id
        ),
        None,
    )
    if migration_item is not None:
        source.setdefault("original_filename", migration_item.get("source_video"))
        source.setdefault("sha256", migration_item.get("source_sha256"))
    source_video, source_path = _source_video(repository, bundle_path, source, manifest)
    source_digest = _string(source.get("sha256")) or _string(
        manifest.get("source_sha256") if manifest else None
    )
    import_facts = _import_facts(operations, recording_id)
    reference = _reference(operations, recording_id)
    review_progress = _review_progress(reference, revisions, source, import_facts)
    annotation_present = import_facts["annotation_present"]
    excluded_reason = _excluded_reason(inspection)

    if inspection is None or bundle_path is None:
        blockers.append("source recording is not present in shared intake")
    else:
        if inspection.state != "complete":
            blockers.append("invalid bundle structure")
        required_source = (
            "sha256",
            "byte_length",
            "original_filename",
            "session_id",
            "table_setup",
        )
        missing_source = [field for field in required_source if not source.get(field)]
        if missing_source:
            blockers.append("metadata or permission missing: " + ", ".join(missing_source))
        if source.get("source_permission") not in {
            "training_only",
            "training_and_evaluation",
            "project_use",
            "unrestricted",
        }:
            blockers.append("metadata or permission missing: source_permission")
        if source.get("retention_state") != "active":
            blockers.append("source retention state is not active")

    blockers.extend(_source_digest_blockers(source_digest, manifest, revisions, bundle_path))
    blockers.extend(_revision_blockers(revisions, reference))
    blockers.extend(str(error) for error in reference["errors"])
    if not annotation_present and reference["state"] != "completed":
        blockers.append("human event annotation is missing")
    if not review_progress["coverage_complete"]:
        blockers.append("incomplete full-recording coverage")
    if review_progress["unresolved_uncertain_events"]:
        blockers.append("unresolved uncertain events")
    blockers.extend(_group_blockers(source))
    blockers.extend(_split_blockers(recording_id, source_digest, split))
    blockers = list(dict.fromkeys(blockers))

    if excluded_reason is not None:
        primary_state = "excluded"
        reason = excluded_reason
    elif inspection is None or bundle_path is None:
        primary_state = "source_missing"
        reason = "restore or collect the source recording before review"
    elif any(item.startswith("metadata or permission missing") for item in blockers):
        primary_state = "metadata_or_permission_missing"
        reason = "repair source metadata or permission before review"
    elif reference["state"] == "completed" and review_progress["coverage_complete"]:
        primary_state = "review_complete"
        reason = "full-recording event review is complete"
    elif not annotation_present and reference["source_revision_id"] is None:
        primary_state = "annotation_missing"
        reason = "review the complete recording and create its event reference"
    elif review_progress["reviewed_item_count"] or review_progress["coverage_percent"]:
        primary_state = "review_in_progress"
        reason = "continue the event review and complete full-recording coverage"
    else:
        primary_state = "annotation_imported_review_required"
        reason = "review the preserved annotation evidence against the complete recording"

    allowed = _allowed_partitions(source)
    eligible = (
        [partition for partition in allowed if partition in PARTITIONS]
        if primary_state == "review_complete" and not blockers
        else []
    )
    partitions = list(split.get("partitions", {}).get(recording_id, ()))
    action = None
    if primary_state not in {"review_complete", "excluded"}:
        action = {
            "recording_id": recording_id,
            "source_video": source_video,
            "reason": reason,
            "workspace_route": (
                f"/recordings/{quote(recording_id, safe='')}/pipeline/events?view=reviewed"
            ),
            "command": (
                f"open the recording workspace for {recording_id}, review the complete "
                "source video, "
                "then publish the maintained event reference"
            ),
        }
    return {
        "recording_id": recording_id,
        "source_video": source_video,
        "source_path": source_path,
        "source_sha256": source_digest,
        "annotation_present": annotation_present,
        "annotation_sha256": import_facts["annotation_sha256"],
        "primary_state": primary_state,
        "reason": reason,
        "blockers": sorted(blockers),
        "review_progress": review_progress,
        "allowed_partitions": allowed,
        "eligible_partitions": eligible,
        "development_partitions": sorted(partitions),
        "maintained_reference": reference,
        "action": action,
        "migration_state": migration.get("states", {}).get(recording_id),
    }


def _bundle_inspections(
    repository: Path, intake: Path, operations: Path
) -> tuple[BundleInspection, ...]:
    try:
        result = inspect_repository(
            repository,
            bundle_root=intake,
            evidence_package_root=operations / ".readiness-no-evidence",
            pending_video_root=operations / ".readiness-no-pending",
            artifacts_root=operations,
        )
    except (OSError, ValueError) as error:
        raise CardEventNetReadinessError(
            f"shared intake could not be inspected: {error}"
        ) from error
    return result.bundles


def _event_revisions(repository: Path, operations: Path) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    root = operations / "pipeline" / "revisions"
    if not root.is_dir():
        return result
    for manifest_path in sorted(root.rglob("manifest.json"), key=lambda item: item.as_posix()):
        manifest = _read_object(manifest_path)
        if manifest is None or manifest.get("content_type") != "events":
            continue
        recording_id = manifest.get("recording_id")
        revision_id = manifest.get("revision_id")
        if not isinstance(recording_id, str) or not isinstance(revision_id, str):
            continue
        content = _read_object(manifest_path.parent / "content.json")
        result.setdefault(recording_id, []).append(
            {
                "path": _relative(manifest_path, repository),
                "revision_id": revision_id,
                "manifest": manifest,
                "content": content,
            }
        )
    for entries in result.values():
        entries.sort(key=lambda item: str(item["revision_id"]))
    return result


def _reference_ids(operations: Path) -> set[str]:
    result: set[str] = set()
    root = operations / "pipeline-references"
    if not root.is_dir():
        return result
    for state_path in sorted(root.rglob("state.json"), key=lambda item: item.as_posix()):
        state = _read_object(state_path)
        recording_id = state.get("recording_id") if state else None
        content_type = state.get("content_type") if state else None
        if isinstance(recording_id, str) and content_type == "events":
            result.add(recording_id)
    return result


def _migration_facts(repository: Path, intake: Path, operations: Path) -> dict[str, Any]:
    path = operations / "cardeventnet-imports" / "migration.json"
    receipt = _read_object(path)
    items = receipt.get("items", []) if receipt else []
    if not isinstance(items, list):
        items = []
    states = {
        item.get("recording_id"): "migrated"
        for item in items
        if isinstance(item, Mapping) and isinstance(item.get("recording_id"), str)
    }
    not_migrated = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        recording_id = item.get("recording_id")
        if not isinstance(recording_id, str) or not (intake / recording_id).is_dir():
            not_migrated.append(recording_id or item.get("video_id", "unknown"))
    return {
        "receipt_path": _relative(path, repository),
        "receipt_state": receipt.get("state") if receipt else "missing",
        "source_count": receipt.get("source_count", 0) if receipt else 0,
        "not_migrated": sorted(str(item) for item in not_migrated),
        "states": states,
        "items": items,
    }


def _active_split(repository: Path, operations: Path) -> dict[str, Any]:
    root = operations / "cardevent-development-split"
    active_path = root / "active.json"
    active = _read_object(active_path)
    if active is None:
        return {"state": "missing", "partitions": {}, "recordings": {}}
    version_id = active.get("split_version_id")
    version = (
        _read_object(root / "versions" / f"{version_id}.json")
        if isinstance(version_id, str)
        else None
    )
    if version is None:
        return {"state": "invalid", "partitions": {}, "recordings": {}}
    partitions = {
        partition: sorted(value)
        for partition in (*PARTITIONS, "unassigned")
        if isinstance(value := version.get(partition), list)
        and all(isinstance(item, str) for item in value)
    }
    by_recording = {
        recording_id: {
            "partition": partition,
            "source_sha256": next(
                (
                    entry.get("source_sha256")
                    for entry in version.get("recordings", [])
                    if isinstance(entry, Mapping) and entry.get("recording_id") == recording_id
                ),
                None,
            ),
        }
        for partition, values in partitions.items()
        for recording_id in values
    }
    return {"state": "valid", "partitions": partitions, "recordings": by_recording}


def _reference(operations: Path, recording_id: str) -> dict[str, Any]:
    root = operations / "pipeline-references" / recording_id / "events"
    state = _read_object(root / "state.json")
    draft = _read_object(root / "draft.json")
    if state is None or draft is None:
        return {
            "state": "missing",
            "draft_revision": None,
            "source_revision_id": None,
            "selected_completed_revision_id": None,
            "draft": None,
            "errors": ["maintained event reference is missing or incomplete"],
        }
    errors: list[str] = []
    if state.get("recording_id") != recording_id or draft.get("recording_id") != recording_id:
        errors.append("maintained event reference recording ID differs")
    if state.get("content_type") != "events" or draft.get("content_type") != "events":
        errors.append("maintained event reference content type differs")
    if state.get("draft_revision") != draft.get("revision"):
        errors.append("maintained event reference revision differs")
    if state.get("source_revision_id") != draft.get("source_revision_id"):
        errors.append("maintained event reference source revision differs")
    return {
        "state": state.get("draft_state", "invalid"),
        "draft_revision": state.get("draft_revision"),
        "source_revision_id": state.get("source_revision_id"),
        "selected_completed_revision_id": state.get("selected_completed_revision_id"),
        "draft": draft,
        "errors": errors,
    }


def _review_progress(
    reference: Mapping[str, Any],
    revisions: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any],
    import_facts: Mapping[str, Any],
) -> dict[str, Any]:
    draft = reference.get("draft")
    raw_items = draft.get("items", []) if isinstance(draft, Mapping) else []
    items = raw_items if isinstance(raw_items, list) else []
    reviewed = [
        item
        for item in items
        if isinstance(item, Mapping) and item.get("review_state") in REVIEWED_ITEM_STATES
    ]
    duration_us = _duration_us(revisions, import_facts, source)
    coverage = draft.get("coverage") if isinstance(draft, Mapping) else None
    coverage_percent, coverage_complete = _coverage_progress(coverage, duration_us)
    uncertain = sum(
        1
        for item in items
        if isinstance(item, Mapping)
        and (
            item.get("review_state") in {"pending", "affected"}
            or item.get("uncertain") is True
            or (isinstance(item.get("item"), Mapping) and item["item"].get("uncertain") is True)
        )
    )
    return {
        "draft_state": reference.get("state"),
        "draft_revision": reference.get("draft_revision"),
        "item_count": len(items),
        "reviewed_item_count": len(reviewed),
        "coverage_percent": coverage_percent,
        "coverage_complete": coverage_complete,
        "coverage_intervals": _coverage_intervals(coverage),
        "unresolved_uncertain_events": uncertain,
        "annotation_event_count": import_facts.get("event_count", len(items)),
    }


def _coverage_progress(coverage: Any, duration_us: int | None) -> tuple[int, bool]:
    if not isinstance(coverage, Mapping) or duration_us is None or duration_us <= 0:
        return 0, False
    intervals = _normalise_intervals(coverage.get("intervals"))
    if not intervals:
        if coverage.get("kind") in {"full_recording", "full-recording"}:
            return 100, True
        return 0, False
    covered = sum(end - start for start, end in intervals)
    percent = min(100, max(0, round(covered * 100 / duration_us)))
    return (
        percent,
        intervals[0][0] == 0
        and intervals[-1][1] == duration_us
        and _has_no_gaps(intervals),
    )


def _coverage_intervals(coverage: Any) -> list[dict[str, int]]:
    return [{"start_us": start, "end_us": end} for start, end in _normalise_intervals(
        coverage.get("intervals") if isinstance(coverage, Mapping) else None
    )]


def _normalise_intervals(value: Any) -> list[tuple[int, int]]:
    if not isinstance(value, list):
        return []
    parsed: list[tuple[int, int]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        start, end = item.get("start_us"), item.get("end_us")
        if (
            isinstance(start, int)
            and not isinstance(start, bool)
            and isinstance(end, int)
            and not isinstance(end, bool)
            and 0 <= start < end
        ):
            parsed.append((start, end))
    parsed.sort()
    merged: list[tuple[int, int]] = []
    for start, end in parsed:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _has_no_gaps(intervals: Sequence[tuple[int, int]]) -> bool:
    return all(
        left[1] == right[0] for left, right in zip(intervals, intervals[1:], strict=False)
    )


def _duration_us(
    revisions: Sequence[Mapping[str, Any]],
    import_facts: Mapping[str, Any],
    source: Mapping[str, Any],
) -> int | None:
    for revision in revisions:
        manifest = revision.get("manifest")
        duration = (
            manifest.get("source", {}).get("duration_us")
            if isinstance(manifest, Mapping)
            else None
        )
        if isinstance(duration, int) and duration > 0:
            return duration
    duration_s = import_facts.get("duration_s", source.get("duration_s"))
    if isinstance(duration_s, (int, float)) and not isinstance(duration_s, bool) and duration_s > 0:
        return round(float(duration_s) * 1_000_000)
    return None


def _source_digest_blockers(
    source_digest: str | None,
    manifest: Mapping[str, Any] | None,
    revisions: Sequence[Mapping[str, Any]],
    bundle_path: Path | None,
) -> list[str]:
    if source_digest is None:
        return []
    blockers: list[str] = []
    if manifest is not None and manifest.get("source_sha256") not in {None, source_digest}:
        blockers.append("source-digest conflict")
    if bundle_path is not None and manifest is not None:
        descriptor = (
            manifest.get("files", {}).get("video")
            if isinstance(manifest.get("files"), Mapping)
            else None
        )
        relative = descriptor.get("relative_path") if isinstance(descriptor, Mapping) else None
        video = bundle_path / PurePosixPath(relative) if isinstance(relative, str) else None
        if video is None or not video.is_file():
            blockers.append("source-digest conflict: canonical video is missing")
        else:
            try:
                if _sha256_file(video) != source_digest:
                    blockers.append("source-digest conflict")
            except OSError:
                blockers.append("source-digest conflict: canonical video is unreadable")
    for revision in revisions:
        revision_source = revision.get("manifest", {}).get("source")
        if (
            isinstance(revision_source, Mapping)
            and revision_source.get("video_sha256") != source_digest
        ):
            blockers.append("source-digest conflict")
    return blockers


def _revision_blockers(
    revisions: Sequence[Mapping[str, Any]], reference: Mapping[str, Any]
) -> list[str]:
    blockers: list[str] = []
    active_ids = {
        reference.get("source_revision_id"),
        reference.get("selected_completed_revision_id"),
    }
    for revision in revisions:
        if revision.get("revision_id") not in active_ids:
            continue
        content = revision.get("content")
        if not isinstance(content, Mapping) or not isinstance(content.get("events"), list):
            blockers.append("invalid event revision")
            continue
        for event in content["events"]:
            if not isinstance(event, Mapping) or event.get("event_type") != "card_state_changed":
                blockers.append("retired event values in an active artifact")
                break
    return blockers


def _group_blockers(source: Mapping[str, Any]) -> list[str]:
    missing = [field for field in GROUP_FIELDS if not source.get(field)]
    if source.get("content_type") == "real_game" and not source.get("game_id"):
        missing.append("game_id")
    return ["missing group metadata: " + ", ".join(missing)] if missing else []


def _split_blockers(
    recording_id: str, source_digest: str | None, split: Mapping[str, Any]
) -> list[str]:
    if split.get("state") == "missing":
        return []
    entry = split.get("recordings", {}).get(recording_id)
    if not isinstance(entry, Mapping):
        return ["stale split membership"]
    if source_digest is not None and entry.get("source_sha256") not in {None, source_digest}:
        return ["stale split membership"]
    return []


def _import_facts(operations: Path, recording_id: str) -> dict[str, Any]:
    root = operations / "cardeventnet-imports" / recording_id
    import_data = _read_object(root / "import.json") or {}
    annotation = root / "annotation.json"
    digest = import_data.get("annotation_sha256")
    return {
        "annotation_present": isinstance(digest, str) or annotation.is_file(),
        "annotation_sha256": digest if isinstance(digest, str) else None,
        "event_count": import_data.get("events_imported", 0),
        "duration_s": (_read_object(root / "metadata.json") or {}).get("duration_s"),
    }


def _excluded_reason(inspection: BundleInspection | None) -> str | None:
    if inspection is None:
        return None
    for task in inspection.tasks:
        if task.task == CARD_EVENTNET_TASK and task.disposition == "excluded":
            return "CardEventNet task enrollment is excluded"
    return None


def _allowed_partitions(source: Mapping[str, Any]) -> list[str]:
    raw = source.get("allowed_uses")
    if not isinstance(raw, list):
        return []
    return sorted({item for item in raw if item in PARTITIONS})


def _source_video(
    repository: Path,
    bundle_path: Path | None,
    source: Mapping[str, Any],
    manifest: Mapping[str, Any] | None,
) -> tuple[str, str | None]:
    original = _string(source.get("original_filename")) or "unknown source video"
    if bundle_path is None or manifest is None:
        return original, None
    descriptor = (
        manifest.get("files", {}).get("video")
        if isinstance(manifest.get("files"), Mapping)
        else None
    )
    relative = descriptor.get("relative_path") if isinstance(descriptor, Mapping) else None
    if not isinstance(relative, str):
        return original, None
    return original, _relative(bundle_path / PurePosixPath(relative), repository)


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (root / path if not path.is_absolute() else path).resolve()


def _relative(path: Path, root: Path | str) -> str:
    try:
        return path.resolve().relative_to(Path(root).resolve()).as_posix() or "."
    except ValueError:
        return path.resolve().as_posix()


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _safe_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= 128 and all(
        character.isalnum() or character in "._:-" for character in value
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = Path()
    finally:
        if temporary != Path():
            temporary.unlink(missing_ok=True)


__all__ = [
    "CARD_EVENTNET_READINESS_RECEIPT_SCHEMA_VERSION",
    "CARD_EVENTNET_READINESS_SCHEMA_VERSION",
    "CARD_EVENTNET_TASK",
    "CardEventNetReadiness",
    "CardEventNetReadinessError",
    "build_cardeventnet_readiness",
    "render_cardeventnet_readiness_human",
    "render_cardeventnet_readiness_json",
    "write_cardeventnet_readiness_receipt",
]
