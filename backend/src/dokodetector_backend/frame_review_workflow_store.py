"""Queue-only frame review progress, separate from maintained references."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Any

from dokodetector_backend.filesystem import atomic_replace_json, contained_path


class FrameReviewWorkflowStore:
    """Persist deferrals and the resume position for one frozen review queue."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self._lock = RLock()

    def path(self, queue_id: str) -> Path:
        return contained_path(self.root, Path(queue_id) / "workflow.json")

    def receipt_path(self, queue_id: str, item_key: str) -> Path:
        receipt_id = hashlib.sha256(item_key.encode("utf-8")).hexdigest()
        return contained_path(self.root, Path(queue_id) / "receipts" / f"{receipt_id}.json")

    def read_receipt(self, queue_id: str, item_key: str) -> dict[str, Any] | None:
        path = self.receipt_path(queue_id, item_key)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def write_receipt(self, queue_id: str, item_key: str, receipt: dict[str, Any]) -> None:
        path = self.receipt_path(queue_id, item_key)
        with self._lock:
            atomic_replace_json(path, receipt)

    def read(self, queue_id: str, queue_digest: str) -> dict[str, Any]:
        path = self.path(queue_id)
        with self._lock:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                value = None
            except (OSError, UnicodeError, json.JSONDecodeError):
                value = None
            if (
                not isinstance(value, dict)
                or value.get("schema_version") != "frame-review-workflow/v1"
                or value.get("queue_id") != queue_id
                or value.get("queue_digest") != queue_digest
                or not isinstance(value.get("deferred_item_keys"), list)
                or not all(isinstance(item, str) for item in value["deferred_item_keys"])
                or (
                    value.get("resume_item_key") is not None
                    and not isinstance(value.get("resume_item_key"), str)
                )
            ):
                return {"deferred_item_keys": [], "resume_item_key": None}
            return {
                "deferred_item_keys": list(dict.fromkeys(value["deferred_item_keys"])),
                "resume_item_key": value.get("resume_item_key"),
            }

    def update(
        self,
        queue_id: str,
        queue_digest: str,
        *,
        action: str,
        item_key: str,
    ) -> dict[str, Any]:
        path = self.path(queue_id)
        with self._lock:
            current = self.read(queue_id, queue_digest)
            deferred = set(current["deferred_item_keys"])
            if action == "defer":
                deferred.add(item_key)
            elif action == "resume":
                deferred.discard(item_key)
            elif action != "set_resume":
                raise ValueError("unsupported queue workflow action")
            value = {
                "schema_version": "frame-review-workflow/v1",
                "queue_id": queue_id,
                "queue_digest": queue_digest,
                "deferred_item_keys": sorted(deferred),
                "resume_item_key": (
                    item_key if action in {"set_resume", "resume"} else current["resume_item_key"]
                ),
            }
            atomic_replace_json(path, value)
            return {
                "deferred_item_keys": value["deferred_item_keys"],
                "resume_item_key": value["resume_item_key"],
            }
