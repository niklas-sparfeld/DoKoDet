from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dokodetector_backend.filesystem import atomic_replace_json
from dokodetector_backend.job_models import JobStorageError


class FakeParticipant:
    """A deterministic domain run and input-protection fixture."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def validate(self, request: dict[str, Any]) -> None:
        if (
            request["type"] not in {"fake", "automated_pipeline"}
            or set(request["context"]) != {"recording_id"}
            or not isinstance(request["context"]["recording_id"], str)
            or set(request["request"]) != {"input"}
            or not isinstance(request["request"]["input"], str)
        ):
            raise ValueError("invalid fake participant request")

    def prepare(
        self, job_id: str, request: dict[str, Any], after_write: Callable[[str], None]
    ) -> None:
        records = (
            (self.root / f"{job_id}.json", {"job_id": job_id, "request": request}, "domain_run"),
            (
                self.root / f"{job_id}.use.json",
                {"job_id": job_id, "input": request["request"]["input"]},
                "accepted_use",
            ),
        )
        for path, expected, point in records:
            if path.exists():
                if json.loads(path.read_text()) != expected:
                    raise JobStorageError("participant identity conflict")
            else:
                atomic_replace_json(path, expected)
                after_write(point)

    def verify(self, job_id: str, request: dict[str, Any]) -> bool:
        try:
            return json.loads((self.root / f"{job_id}.json").read_text()) == {
                "job_id": job_id,
                "request": request,
            } and json.loads((self.root / f"{job_id}.use.json").read_text()) == {
                "job_id": job_id,
                "input": request["request"]["input"],
            }
        except (OSError, ValueError):
            return False
