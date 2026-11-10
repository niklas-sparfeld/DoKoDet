"""Concrete immutable event-set versions stored under a recording folder."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doko_operations.pipeline_data import EventData

from dokodetector_backend.filesystem import atomic_write_json, contained_path
from dokodetector_backend.recording_folder_store import (
    RecordingFolderStore,
)


class EventSetError(ValueError):
    """An event set is invalid or could not be safely stored."""


class EventSetStore:
    """Save complete immutable versions and select exact references in recording HEAD."""

    def __init__(self, recordings: RecordingFolderStore) -> None:
        self.recordings = recordings

    def save(
        self,
        recording_id: str,
        *,
        set_id: str,
        version: str,
        content: dict[str, Any],
        origin: str,
        provenance: dict[str, Any],
    ) -> dict[str, Any]:
        set_id = _safe_identifier(set_id, "event-set ID")
        version = _safe_identifier(version, "event-set version")
        root = self.recordings.get(recording_id)
        if root is None:
            raise EventSetError("recording does not exist")
        parsed = EventData.from_mapping(content)
        if origin not in {"processor", "manual", "corrected"}:
            raise EventSetError("event set origin is invalid")
        if not isinstance(provenance, dict):
            raise EventSetError("event set provenance must be an object")
        base = contained_path(self.recordings.recording_path(recording_id) / "event-sets", set_id)
        destination = contained_path(base / "versions", version)
        if destination.exists() or destination.is_symlink():
            raise EventSetError("event set version already exists")
        base.mkdir(parents=True, exist_ok=True)
        versions = destination.parent
        versions.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".event-set-", dir=versions))
        entries = []
        try:
            event_dir = staging / "events"
            event_dir.mkdir()
            for event in parsed.events:
                event_value = {
                    "schema_version": "event/v1",
                    **event.to_mapping(),
                }
                relative_path = f"events/{event.event_id}/event.json"
                target = staging / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    json.dumps(event_value, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8",
                )
                entries.append({"event_id": event.event_id, "relative_path": relative_path})
            metadata = {
                "schema_version": "event-set/v1",
                "recording_id": recording_id,
                "set_id": set_id,
                "version": version,
                "events": entries,
                "source": provenance.get("source"),
                "provenance": provenance,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "origin": origin,
            }
            (staging / "event-set.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            for path in staging.rglob("*"):
                if path.is_file():
                    with path.open("rb") as handle:
                        os.fsync(handle.fileno())
            directories = sorted(
                (path for path in staging.rglob("*") if path.is_dir()),
                key=lambda item: len(item.parts),
                reverse=True,
            )
            for directory in directories:
                _fsync_directory(directory)
            _fsync_directory(staging)
            os.rename(staging, destination)
            _fsync_directory(versions)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return {**metadata, "content": parsed.to_mapping()}

    def get(self, recording_id: str, set_id: str, version: str) -> dict[str, Any] | None:
        try:
            set_id = _safe_identifier(set_id, "event-set ID")
            version = _safe_identifier(version, "event-set version")
            folder = contained_path(
                self.recordings.recording_path(recording_id) / "event-sets" / set_id / "versions",
                version,
            )
            if folder.is_symlink() or not folder.is_dir():
                return None
            raw = json.loads((folder / "event-set.json").read_text(encoding="utf-8"))
            if (
                set(raw)
                != {
                    "schema_version",
                    "recording_id",
                    "set_id",
                    "version",
                    "events",
                    "source",
                    "provenance",
                    "created_at",
                    "origin",
                }
                or raw.get("schema_version") != "event-set/v1"
                or raw.get("recording_id") != recording_id
                or raw.get("set_id") != set_id
                or raw.get("version") != version
            ):
                return None
            events = []
            for item in raw["events"]:
                if set(item) != {"event_id", "relative_path"} or item["relative_path"] != (
                    f"events/{item['event_id']}/event.json"
                ):
                    return None
                path = contained_path(folder, item["relative_path"])
                event = json.loads(path.read_text(encoding="utf-8"))
                if (
                    event.get("schema_version") != "event/v1"
                    or event.get("event_id") != item["event_id"]
                ):
                    return None
                events.append(
                    {key: value for key, value in event.items() if key != "schema_version"}
                )
            content = EventData.from_mapping({"schema_version": "event-data/v1", "events": events})
            content_mapping = content.to_mapping()
            content_bytes = json.dumps(
                content_mapping, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
            return {
                **raw,
                "content": content_mapping,
                "content_sha256": hashlib.sha256(content_bytes).hexdigest(),
            }
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def select(
        self,
        recording_id: str,
        *,
        choice: str,
        reference: dict[str, str] | None,
        expected_version: int,
    ) -> dict[str, Any]:
        if choice not in {"generated", "reference"}:
            raise EventSetError("event-set choice is invalid")
        if reference is not None and (
            set(reference) != {"set_id", "version"}
            or not isinstance(reference.get("set_id"), str)
            or not isinstance(reference.get("version"), str)
            or self.get(recording_id, reference["set_id"], reference["version"]) is None
        ):
            raise EventSetError("selected event-set version is unavailable")
        root = self.recordings.get(recording_id)
        if root is None:
            raise EventSetError("recording does not exist")
        path = self.recordings.recording_path(recording_id) / "recording.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        head = dict(value["head"])
        event_head = dict(head.get("events", {}))
        event_head[choice] = reference
        head["events"] = event_head
        value["head"] = head
        updated = self.recordings.replace_root(
            recording_id, value, expected_version=expected_version
        )
        return {"recording_version": updated.version, "head": updated.head}

    def get_selection(self, recording_id: str) -> dict[str, Any] | None:
        root = self.recordings.get(recording_id)
        if root is None:
            return None
        events = root.head.get("events", {})
        if not isinstance(events, dict) or set(events) - {"generated", "reference"}:
            raise EventSetError("event-set selection in recording HEAD is invalid")
        result = {}
        for choice in ("generated", "reference"):
            reference = events.get(choice)
            if reference is not None and (
                not isinstance(reference, dict)
                or set(reference) != {"set_id", "version"}
                or not isinstance(reference["set_id"], str)
                or not isinstance(reference["version"], str)
                or self.get(recording_id, reference["set_id"], reference["version"]) is None
            ):
                raise EventSetError(f"event-set {choice} reference in recording HEAD is invalid")
            result[choice] = reference
        return {
            "schema_version": "event-set-selection/v1",
            "recording_id": recording_id,
            "recording_version": root.version,
            "generated": result["generated"],
            "reference": result["reference"],
        }

    def save_review(
        self,
        recording_id: str,
        set_id: str,
        version: str,
        *,
        review_id: str,
        kind: str,
        question: str,
        decision: str | None,
        reviewer: dict[str, Any],
        evidence: dict[str, Any],
        item_id: str | None = None,
        coverage: dict[str, Any] | None = None,
        reviewed_at: str | None = None,
    ) -> dict[str, Any]:
        """Save one immutable review beside an exact event-set version."""
        _safe_identifier(review_id, "review ID")
        event_set = self.get(recording_id, set_id, version)
        if event_set is None:
            raise EventSetError("reviewed event-set version is unavailable")
        if kind not in {"item", "coverage", "overall"}:
            raise EventSetError("event review kind is invalid")
        if not isinstance(question, str) or not question.strip():
            raise EventSetError("review question must not be empty")
        if kind == "coverage":
            if (
                decision is not None
                or item_id is not None
                or not isinstance(coverage, dict)
                or not coverage
            ):
                raise EventSetError("coverage review needs a non-empty scope and no decision")
            details = {"coverage": coverage}
        else:
            if not isinstance(decision, str) or not decision.strip():
                raise EventSetError("event review decision must not be empty")
            if kind == "item":
                if not isinstance(item_id, str) or coverage is not None:
                    raise EventSetError("item review needs one event ID and no coverage scope")
                event = next(
                    (row for row in event_set["content"]["events"] if row["event_id"] == item_id),
                    None,
                )
                if event is None:
                    raise EventSetError("reviewed event is not present in the event set")
                item_bytes = json.dumps(
                    event, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
                details = {
                    "item_id": item_id,
                    "item_sha256": hashlib.sha256(item_bytes).hexdigest(),
                }
            else:
                if item_id is not None or coverage is not None:
                    raise EventSetError("overall review cannot include item or coverage details")
                details = {}
        if (
            not isinstance(reviewer, dict)
            or not reviewer
            or not isinstance(evidence, dict)
            or not evidence
        ):
            raise EventSetError("reviewer and evidence must be non-empty objects")
        if reviewed_at is not None:
            try:
                timestamp = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            except (AttributeError, TypeError, ValueError) as error:
                raise EventSetError("review timestamp must be an ISO 8601 value") from error
            if timestamp.tzinfo is None:
                raise EventSetError("review timestamp must include a timezone")
        content_bytes = json.dumps(
            event_set["content"], sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        record = {
            "schema_version": "event-review/v1",
            "review_id": review_id,
            "set_id": set_id,
            "version": version,
            "content_sha256": hashlib.sha256(content_bytes).hexdigest(),
            "kind": kind,
            "question": question,
            "decision": decision,
            "reviewer": reviewer,
            "evidence": evidence,
            **details,
            "reviewed_at": reviewed_at or datetime.now(timezone.utc).isoformat(),
        }
        directory = contained_path(
            self.recordings.recording_path(recording_id) / "event-sets",
            f"{set_id}/reviews",
        )
        directory.mkdir(parents=True, exist_ok=True)
        path = contained_path(directory, f"{review_id}.json")
        lock_path = self.recordings.recording_path(recording_id) / ".recording.lock"
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            if path.exists() or path.is_symlink():
                previous = json.loads(path.read_text(encoding="utf-8"))
                if {key: value for key, value in previous.items() if key != "reviewed_at"} != {
                    key: value for key, value in record.items() if key != "reviewed_at"
                }:
                    raise EventSetError("review ID is already used by another decision")
                return previous
            atomic_write_json(path, record)
        return record

    def list_reviews(self, recording_id: str, set_id: str, version: str) -> list[dict[str, Any]]:
        event_set = self.get(recording_id, set_id, version)
        if event_set is None:
            raise EventSetError("event-set version is unavailable")
        directory = self.recordings.recording_path(recording_id) / "event-sets" / set_id / "reviews"
        if not directory.is_dir() or directory.is_symlink():
            return []
        result = []
        for path in sorted(directory.glob("*.json")):
            if path.is_symlink():
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("set_id") != set_id or record.get("version") != version:
                continue
            kind = record.get("kind")
            expected = {
                "schema_version",
                "review_id",
                "set_id",
                "version",
                "content_sha256",
                "kind",
                "question",
                "decision",
                "reviewer",
                "evidence",
                "reviewed_at",
            }
            if kind == "item":
                expected.update({"item_id", "item_sha256"})
            elif kind == "coverage":
                expected.add("coverage")
            elif kind != "overall":
                raise EventSetError("event review kind is invalid")
            if (
                set(record) != expected
                or record.get("schema_version") != "event-review/v1"
                or record.get("review_id") != path.stem
                or record.get("content_sha256") != event_set["content_sha256"]
                or not isinstance(record.get("question"), str)
                or not record["question"].strip()
                or not isinstance(record.get("reviewer"), dict)
                or not record["reviewer"]
                or not isinstance(record.get("evidence"), dict)
                or not record["evidence"]
                or (
                    kind == "coverage"
                    and (record.get("decision") is not None or not record.get("coverage"))
                )
                or (
                    kind != "coverage"
                    and (
                        not isinstance(record.get("decision"), str)
                        or not record["decision"].strip()
                    )
                )
            ):
                raise EventSetError("event review record is invalid")
            if kind == "item":
                item = next(
                    (
                        row
                        for row in event_set["content"]["events"]
                        if row["event_id"] == record["item_id"]
                    ),
                    None,
                )
                if item is None:
                    raise EventSetError("event review item is not in its exact event set")
                digest = hashlib.sha256(
                    json.dumps(
                        item, sort_keys=True, separators=(",", ":"), allow_nan=False
                    ).encode()
                ).hexdigest()
                if record["item_sha256"] != digest:
                    raise EventSetError("event review item digest does not match")
            result.append(record)
        return result


def _safe_identifier(value: str, field: str) -> str:
    pattern = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise EventSetError(f"{field} must be a safe identifier")
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
