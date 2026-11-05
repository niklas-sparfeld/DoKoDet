"""Preflight and durable records for recording-scoped automated pipeline runs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from doko_operations.pipeline_data import RecordingVideoSource

from dokodetector_backend.round_analysis_contract import AnalysisSearchLimits

try:
    from fcntl import LOCK_EX, LOCK_UN, flock
except ImportError:  # pragma: no cover - supported local platforms provide fcntl.
    LOCK_EX = LOCK_UN = 0

    def flock(_descriptor: int, _operation: int) -> None:
        return None


PIPELINE_STAGE_NAMES = (
    "event_proposals",
    "visible_card_and_pile_proposals",
    "card_scene_and_calibration",
    "visual_identity_proposals",
    "table_observations",
    "reconstruction",
)
ACTIVE_STATES = {"accepted", "queued", "running"}


class AutomatedPipelinePreflightError(ValueError):
    """The requested run is missing valid inputs before any stage starts."""

    def __init__(self, blockers: list[str]) -> None:
        self.blockers = blockers
        super().__init__("; ".join(blockers))


class AutomatedPipelineRunConflict(RuntimeError):
    """A recording already has an active run or an idempotency key was reused."""

    def __init__(self, message: str, *, active_run_id: str | None = None) -> None:
        self.active_run_id = active_run_id
        super().__init__(message)


class AutomatedPipelineRunNotFound(LookupError):
    """The requested overall run does not exist."""


class AutomatedPipelineRunStore:
    """Atomically persist overall run records and per-recording active pointers."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.runs_root = root / "runs"
        self.active_root = root / "active"
        self.idempotency_root = root / "idempotency"
        self._lock = threading.RLock()

    @contextmanager
    def locked_recording(self, recording_id: str):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f".{_safe_id(recording_id)}.lock"
        with self._lock, path.open("a+b") as stream:
            flock(stream.fileno(), LOCK_EX)
            try:
                yield
            finally:
                flock(stream.fileno(), LOCK_UN)

    def create(self, document: Mapping[str, Any]) -> None:
        recording_id = str(document["recording_id"])
        run_id = str(document["run_id"])
        self.runs_root.mkdir(parents=True, exist_ok=True)
        _atomic_json(self._run_path(run_id), document)
        _atomic_json(self._active_path(recording_id), {"run_id": run_id})

    def get(self, run_id: str) -> dict[str, Any]:
        path = self._run_path(run_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise AutomatedPipelineRunNotFound(f"Pipeline run was not found: {run_id}") from error
        if not isinstance(value, dict):
            raise ValueError("Stored pipeline run must be a JSON object.")
        return value

    def get_active(self, recording_id: str) -> dict[str, Any] | None:
        try:
            pointer = json.loads(self._active_path(recording_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        run_id = pointer.get("run_id") if isinstance(pointer, dict) else None
        return self.get(run_id) if isinstance(run_id, str) else None

    def resumable(self) -> list[dict[str, Any]]:
        """Return accepted or interrupted runs for worker startup recovery."""
        if not self.runs_root.exists():
            return []
        documents = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(self.runs_root.glob("*.json"))
        ]
        return [document for document in documents if document.get("status") in ACTIVE_STATES]

    def update(self, run_id: str, mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        """Atomically update one run document."""
        document = self.get(run_id)
        with self.locked_recording(str(document["recording_id"])):
            document = self.get(run_id)
            mutate(document)
            document["updated_at"] = _now()
            _atomic_json(self._run_path(run_id), document)
            return document

    def get_idempotent(self, recording_id: str, key: str) -> dict[str, Any] | None:
        try:
            pointer = json.loads(
                self._idempotency_path(recording_id, key).read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return None
        run_id = pointer.get("run_id") if isinstance(pointer, dict) else None
        return self.get(run_id) if isinstance(run_id, str) else None

    def finish(self, run_id: str, *, status: str) -> dict[str, Any]:
        if status not in {"complete", "failed", "cancelled"}:
            raise ValueError("A terminal pipeline status is required.")
        document = self.get(run_id)
        recording_id = str(document["recording_id"])
        with self.locked_recording(recording_id):
            document = self.get(run_id)
            document["status"] = status
            document["updated_at"] = _now()
            _atomic_json(self._run_path(run_id), document)
            active = self.get_active(recording_id)
            if active is not None and active["run_id"] == run_id:
                self._active_path(recording_id).unlink(missing_ok=True)
            return document

    def save_idempotency(self, recording_id: str, key: str, run_id: str) -> None:
        self.idempotency_root.mkdir(parents=True, exist_ok=True)
        _atomic_json(self._idempotency_path(recording_id, key), {"run_id": run_id})

    def _run_path(self, run_id: str) -> Path:
        return self.runs_root / f"{_safe_id(run_id)}.json"

    def _active_path(self, recording_id: str) -> Path:
        return self.active_root / f"{_safe_id(recording_id)}.json"

    def _idempotency_path(self, recording_id: str, key: str) -> Path:
        name = hashlib.sha256(f"{recording_id}:{key}".encode()).hexdigest()
        return self.idempotency_root / f"{name}.json"


class AutomatedPipelineRunService:
    """Validate all start inputs, freeze them, and create one durable overall run."""

    def __init__(
        self,
        *,
        store: AutomatedPipelineRunStore,
        recording_source_provider: Callable[[str], RecordingVideoSource],
        recording_provider_validator: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
        round_session_provider: Callable[[str], str],
    ) -> None:
        self.store = store
        self.recording_source_provider = recording_source_provider
        self.recording_provider_validator = recording_provider_validator
        self.round_session_provider = round_session_provider

    def start(self, recording_id: str, request: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        normalized = self._validate_request(request)
        idempotency_key = str(normalized["idempotency_key"])
        client_request_digest = _digest(normalized)
        with self.store.locked_recording(recording_id):
            previous = self.store.get_idempotent(recording_id, idempotency_key)
            if previous is not None:
                if previous["client_request_sha256"] != client_request_digest:
                    raise AutomatedPipelineRunConflict(
                        "This idempotency key already identifies a different run."
                    )
                return previous, True
            active = self.store.get_active(recording_id)
            if active is not None and active["status"] in ACTIVE_STATES:
                raise AutomatedPipelineRunConflict(
                    "This recording already has an active pipeline run.",
                    active_run_id=str(active["run_id"]),
                )

            try:
                source = self.recording_source_provider(recording_id)
                session_id = self.round_session_provider(recording_id)
            except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
                raise AutomatedPipelinePreflightError([str(error)]) from error
            normalized.update(_automatic_round_context(recording_id, session_id))
            try:
                validated = self.recording_provider_validator(
                    recording_id, normalized["stage_requests"]
                )
            except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
                raise AutomatedPipelinePreflightError([str(error)]) from error
            if isinstance(validated.get("stage_requests"), Mapping):
                normalized["stage_requests"] = dict(validated["stage_requests"])
            normalized["source"] = source.to_mapping()
            normalized["resolved_providers"] = dict(validated.get("providers", {}))
            request_digest = _digest(normalized)

            run_id = str(uuid4())
            now = _now()
            document = {
                "schema_version": "automated-pipeline-run/v1",
                "run_id": run_id,
                "recording_id": recording_id,
                "status": "accepted",
                "created_at": now,
                "updated_at": now,
                "source": source.to_mapping(),
                "request_sha256": request_digest,
                "client_request_sha256": client_request_digest,
                "request": normalized,
                "resolved_providers": dict(validated.get("providers", {})),
                "failure": None,
                "stages": [
                    {"name": name, "status": "pending", "run_id": None}
                    for name in PIPELINE_STAGE_NAMES
                ],
            }
            self.store.create(document)
            self.store.save_idempotency(recording_id, idempotency_key, run_id)
            return document, False

    def read(self, run_id: str) -> dict[str, Any]:
        return self.store.get(run_id)

    def _validate_request(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise AutomatedPipelinePreflightError(["The start request must be an object."])
        stage_requests = request.get("stage_requests")
        if not isinstance(stage_requests, Mapping):
            raise AutomatedPipelinePreflightError(["Provide frozen settings for every stage."])
        required = set(PIPELINE_STAGE_NAMES) - {"reconstruction"}
        if set(stage_requests) != required:
            missing = sorted(required - set(stage_requests))
            extra = sorted(set(stage_requests) - required)
            blockers = []
            if missing:
                blockers.append("Missing stage settings: " + ", ".join(missing) + ".")
            if extra:
                blockers.append("Unknown stage settings: " + ", ".join(extra) + ".")
            raise AutomatedPipelinePreflightError(blockers)
        if any(not isinstance(value, Mapping) for value in stage_requests.values()):
            raise AutomatedPipelinePreflightError(["Each stage setting must be an object."])
        missing_configuration = [
            name
            for name in sorted(required)
            if not isinstance(stage_requests[name].get("configuration"), Mapping)
        ]
        if missing_configuration:
            raise AutomatedPipelinePreflightError(
                [f"Provide configuration for {name}." for name in missing_configuration]
            )

        search = request.get("search")
        blockers: list[str] = []
        try:
            limits = AnalysisSearchLimits.model_validate(search)
        except Exception as error:
            blockers.append(f"Search limits are missing or invalid: {error}")
            limits = None
        if request.get("rules_version") != "v1":
            blockers.append("Rules version must be v1.")
        try:
            UUID(str(request.get("idempotency_key")))
        except (ValueError, TypeError, AttributeError):
            blockers.append("Provide a UUID idempotency_key.")
        if blockers:
            raise AutomatedPipelinePreflightError(blockers)
        assert limits is not None

        frozen = dict(request)
        frozen["idempotency_key"] = str(UUID(str(request["idempotency_key"])))
        frozen["search"] = limits.model_dump(mode="json")
        frozen["stage_requests"] = {
            name: _json_value(stage_requests[name]) for name in sorted(required)
        }
        return _json_value(frozen)


def _automatic_round_context(recording_id: str, session_id: str) -> dict[str, Any]:
    """Build stable analysis identifiers and generic seats without operator input."""

    suffix = hashlib.sha256(recording_id.encode()).hexdigest()[:16]
    round_id = f"round-{suffix}"
    return {
        "session_id": session_id,
        "round_id": round_id,
        "round_context": {
            "game_id": f"game-{suffix}",
            "round_id": round_id,
            "active_players": ["player-1", "player-2", "player-3", "player-4"],
            "dealer": "dealer-unspecified",
            "first_trick_leader": "player-1",
        },
    }


def _json_value(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True))


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _safe_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


__all__ = [
    "AutomatedPipelinePreflightError",
    "AutomatedPipelineRunConflict",
    "AutomatedPipelineRunNotFound",
    "AutomatedPipelineRunService",
    "AutomatedPipelineRunStore",
    "PIPELINE_STAGE_NAMES",
]
