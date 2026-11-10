"""Concrete immutable event-set versions stored under a recording folder."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doko_operations.pipeline_data import EventData

from dokodetector_backend.filesystem import contained_path
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
            return {**raw, "content": content.to_mapping()}
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
