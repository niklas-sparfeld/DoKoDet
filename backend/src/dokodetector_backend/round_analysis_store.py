"""Validated filesystem storage for round-analysis lifecycle state."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import UUID

from dokodetector_backend.filesystem import (
    atomic_replace_json,
    commit_staged_directory,
    contained_path,
    enumerate_resource_directories,
    staging_directory,
)
from dokodetector_backend.round_analysis_contract import (
    ROUND_ANALYSIS_STATES,
    RoundAnalysisCreateRequest,
    canonical_analysis_request_bytes,
    canonical_analysis_request_sha256,
    parse_round_analysis_create_request_bytes,
)
from dokodetector_backend.round_analysis_storage import RoundAnalysisArtifactStorage
from dokodetector_backend.stored_models import StoredRoundAnalysis

LOGGER = logging.getLogger(__name__)
RESTART_ANALYSIS_ERROR = "The analysis did not finish before the backend restarted."
ROUND_ANALYSIS_STATE_SCHEMA_VERSION = "round-analysis-state/v1"
ROUND_ANALYSIS_RESULT_STATUSES = ("resolved", "ambiguous", "incomplete", "impossible")
_SHA256_LENGTH = 64


class RoundAnalysisStoreError(RuntimeError):
    """The canonical round-analysis state could not be read or written."""


class RoundAnalysisConflict(RoundAnalysisStoreError):
    """An analysis ID is already stored with different request content."""


class RoundAnalysisNotFound(RoundAnalysisStoreError):
    """The requested round analysis does not exist."""


@dataclass(frozen=True, slots=True)
class RoundAnalysisInsert:
    """The result of an idempotent analysis insert."""

    analysis: StoredRoundAnalysis
    created: bool


class RoundAnalysisStore:
    """Create, read, and atomically update round-analysis state documents."""

    def __init__(self, artifact_storage: RoundAnalysisArtifactStorage) -> None:
        self.artifact_storage = artifact_storage
        self.root = artifact_storage.root
        self._lock = RLock()

    def analysis_path(self, analysis_id: UUID | str) -> Path:
        """Return the canonical directory for one validated analysis ID."""

        return contained_path(self.root, str(UUID(str(analysis_id))))

    def get(self, analysis_id: UUID | str) -> StoredRoundAnalysis | None:
        """Read one valid analysis state, or return ``None`` when it is unavailable."""

        try:
            path = self.analysis_path(analysis_id)
        except (TypeError, ValueError):
            return None
        try:
            return self._read_path(path)
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            if path.exists() or path.is_symlink():
                self._log_invalid(path, error)
            return None

    def list(self) -> tuple[StoredRoundAnalysis, ...]:
        """Return valid analyses in stable newest-first order."""

        enumeration = enumerate_resource_directories(
            self.root,
            validate=self._read_path,
        )
        for diagnostic in enumeration.diagnostics:
            self._log_invalid(diagnostic.path, ValueError(diagnostic.reason))
        analyses: list[StoredRoundAnalysis] = []
        for path in enumeration.paths:
            try:
                analyses.append(self._read_path(path))
            except (OSError, TypeError, UnicodeError, ValueError) as error:
                self._log_invalid(path, error)
        return tuple(
            sorted(
                analyses,
                key=lambda analysis: (analysis.created_at, str(analysis.analysis_id)),
                reverse=True,
            )
        )

    def list_by_recording(self, recording_id: str) -> tuple[StoredRoundAnalysis, ...]:
        """Return valid analyses for one recording, newest first."""

        return tuple(
            analysis for analysis in self.list() if analysis.recording_id == recording_id
        )

    def create(
        self,
        request: RoundAnalysisCreateRequest,
        *,
        created_at: datetime | None = None,
    ) -> RoundAnalysisInsert:
        """Create one queued state document or replay an identical request."""

        analysis, created = self.insert(
            StoredRoundAnalysis.from_request(request, created_at=created_at)
        )
        return RoundAnalysisInsert(analysis=analysis, created=created)

    def insert(self, analysis: StoredRoundAnalysis) -> tuple[StoredRoundAnalysis, bool]:
        """Atomically publish one queued state document or return an identical replay."""

        with self._lock:
            destination = self.analysis_path(analysis.analysis_id)
            if destination.exists() or destination.is_symlink():
                try:
                    existing = self._read_path(destination)
                except (OSError, TypeError, UnicodeError, ValueError) as error:
                    raise RoundAnalysisStoreError(
                        "The existing round analysis state is invalid."
                    ) from error
                if _same_request(existing, analysis):
                    return existing, False
                raise RoundAnalysisConflict(
                    "The analysis ID is already stored with different request content."
                )

            payload = _state_payload(analysis)
            with staging_directory(self.root, prefix=f".{analysis.analysis_id}-") as staging:
                atomic_replace_json(
                    staging / "state.json",
                    payload,
                    validate=lambda raw: self._parse_state(
                        raw,
                        staging,
                        require_canonical_name=False,
                    ),
                )
                commit_staged_directory(
                    staging,
                    destination,
                    validate=lambda path: self._read_path(path, require_canonical_name=False),
                )
            stored = self._read_path(destination)
            return stored, True

    def update_progress(
        self,
        analysis_id: UUID | str,
        *,
        state: str,
        completed: int,
        started_at: datetime | None = None,
    ) -> StoredRoundAnalysis:
        """Atomically update a non-terminal state without allowing regressions."""

        if state not in {"queued", "analyzing_evidence", "reconstructing"}:
            raise ValueError("progress state must be non-terminal.")
        if completed < 0:
            raise ValueError("completed evidence packages must not be negative.")
        with self._lock:
            analysis = self._require(analysis_id)
            if analysis.state in {"complete", "failed"}:
                raise ValueError("a terminal analysis cannot receive progress updates.")
            allowed_states = {
                "queued": {"queued", "analyzing_evidence"},
                "analyzing_evidence": {"analyzing_evidence", "reconstructing"},
                "reconstructing": {"reconstructing"},
            }
            if state not in allowed_states[analysis.state]:
                raise ValueError(f"analysis state cannot change from {analysis.state} to {state}.")
            if completed < analysis.completed_evidence_packages:
                raise ValueError("completed evidence packages cannot regress.")
            if completed > analysis.total_evidence_packages:
                raise ValueError("completed evidence packages cannot exceed the total.")
            if started_at is None and state != "queued" and analysis.started_at is None:
                started_at = datetime.now(timezone.utc)
            updated = replace(
                analysis,
                state=state,
                completed_evidence_packages=completed,
                started_at=started_at if started_at is not None else analysis.started_at,
            )
            return self._replace_state(updated)

    def mark_complete(
        self,
        analysis_id: UUID | str,
        *,
        result_status: str,
        result_json: str,
        input_artifact_id: str,
        input_artifact_sha256: str,
        result_artifact_id: str,
        result_artifact_sha256: str,
        completed_at: datetime | None = None,
    ) -> StoredRoundAnalysis:
        """Commit complete state only after both immutable artifacts validate."""

        if result_status not in ROUND_ANALYSIS_RESULT_STATUSES:
            raise ValueError("invalid reconstruction result status.")
        if not result_json:
            raise ValueError("a complete analysis needs a result status and JSON.")
        if completed_at is None:
            completed_at = datetime.now(timezone.utc)
        with self._lock:
            analysis = self._require(analysis_id)
            if analysis.state in {"complete", "failed"}:
                raise ValueError("a terminal analysis cannot be completed again.")
            completed = replace(
                analysis,
                state="complete",
                completed_evidence_packages=analysis.total_evidence_packages,
                result_status=result_status,
                result_json=result_json,
                error=None,
                input_artifact_id=input_artifact_id,
                input_artifact_sha256=input_artifact_sha256,
                result_artifact_id=result_artifact_id,
                result_artifact_sha256=result_artifact_sha256,
                completed_at=completed_at,
            )
            self._validate_complete_artifacts(completed, self.analysis_path(analysis.analysis_id))
            return self._replace_state(completed)

    def mark_failed(
        self,
        analysis_id: UUID | str,
        error: str,
        *,
        completed_at: datetime | None = None,
    ) -> StoredRoundAnalysis:
        """Atomically store a short terminal failure message."""

        if not error or len(error) > 512:
            raise ValueError("analysis errors must contain 1 to 512 characters.")
        if completed_at is None:
            completed_at = datetime.now(timezone.utc)
        with self._lock:
            analysis = self._require(analysis_id)
            if analysis.state in {"complete", "failed"}:
                raise ValueError("a terminal analysis cannot be failed again.")
            failed = replace(
                analysis,
                state="failed",
                result_status=None,
                result_json=None,
                error=error,
                result_artifact_id=None,
                result_artifact_sha256=None,
                completed_at=completed_at,
            )
            return self._replace_state(failed)

    def fail_non_terminal(self, *, now: datetime | None = None) -> int:
        """Convert all valid interrupted analyses to the restart failure."""

        if now is None:
            now = datetime.now(timezone.utc)
        converted = 0
        with self._lock:
            for analysis in self.list():
                if analysis.state in {"complete", "failed"}:
                    continue
                self._replace_state(
                    replace(
                        analysis,
                        state="failed",
                        result_status=None,
                        result_json=None,
                        error=RESTART_ANALYSIS_ERROR,
                        result_artifact_id=None,
                        result_artifact_sha256=None,
                        completed_at=now,
                    )
                )
                converted += 1
        return converted

    def _require(self, analysis_id: UUID | str) -> StoredRoundAnalysis:
        analysis = self.get(analysis_id)
        if analysis is None:
            raise RoundAnalysisNotFound("The round analysis was not found.")
        return analysis

    def _replace_state(self, analysis: StoredRoundAnalysis) -> StoredRoundAnalysis:
        path = self.analysis_path(analysis.analysis_id)
        atomic_replace_json(
            path / "state.json",
            _state_payload(analysis),
            validate=lambda raw: self._parse_state(
                raw,
                path,
                validate_artifacts=analysis.state == "complete",
            ),
        )
        return self._read_path(path)

    def _read_path(self, path: Path, *, require_canonical_name: bool = True) -> StoredRoundAnalysis:
        if path.is_symlink() or not path.is_dir():
            raise OSError("round analysis directory is unavailable")
        state_path = path / "state.json"
        if state_path.is_symlink() or not state_path.is_file():
            raise OSError("round analysis state.json is unavailable")
        return self._parse_state(
            state_path.read_bytes(),
            path,
            require_canonical_name=require_canonical_name,
        )

    def _parse_state(
        self,
        raw: bytes,
        directory: Path,
        *,
        require_canonical_name: bool = True,
        validate_artifacts: bool = False,
    ) -> StoredRoundAnalysis:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("round analysis state is not valid UTF-8 JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("round analysis state must be an object")
        expected_fields = {
            "schema_version",
            "analysis_id",
            "recording_id",
            "round_id",
            "session_id",
            "request_json",
            "request_sha256",
            "state",
            "total_evidence_packages",
            "completed_evidence_packages",
            "result_status",
            "result_json",
            "error",
            "input_artifact_id",
            "input_artifact_sha256",
            "result_artifact_id",
            "result_artifact_sha256",
            "created_at",
            "started_at",
            "completed_at",
        }
        if set(payload) != expected_fields:
            raise ValueError("round analysis state fields are invalid")
        if payload["schema_version"] != ROUND_ANALYSIS_STATE_SCHEMA_VERSION:
            raise ValueError("round analysis state schema version is invalid")

        try:
            analysis_id = UUID(_string(payload, "analysis_id"))
            session_id = UUID(_string(payload, "session_id"))
            request_json = _string(payload, "request_json")
            request = parse_round_analysis_create_request_bytes(request_json.encode("utf-8"))
        except (TypeError, UnicodeError, ValueError) as error:
            raise ValueError("round analysis request is invalid") from error
        if analysis_id != request.analysis_id or (
            require_canonical_name and str(analysis_id) != directory.name
        ):
            raise ValueError("round analysis ID does not match its state directory")
        if _string(payload, "recording_id") != request.recording_id:
            raise ValueError("round analysis recording ID does not match its request")
        if _string(payload, "round_id") != request.round_id:
            raise ValueError("round analysis round ID does not match its request")
        if session_id != request.session_id:
            raise ValueError("round analysis session ID does not match its request")
        request_bytes = canonical_analysis_request_bytes(request)
        if request_json != request_bytes.decode("utf-8"):
            raise ValueError("round analysis request is not canonical")
        if payload["request_sha256"] != canonical_analysis_request_sha256(request):
            raise ValueError("round analysis request digest is invalid")

        state = _string(payload, "state")
        if state not in ROUND_ANALYSIS_STATES:
            raise ValueError("round analysis state is invalid")
        total = _non_negative_int(payload, "total_evidence_packages")
        completed = _non_negative_int(payload, "completed_evidence_packages")
        if total != len(request.evidence_package_ids) or completed > total:
            raise ValueError("round analysis package counts are invalid")
        result_status = _optional_string(payload, "result_status")
        if result_status is not None and result_status not in ROUND_ANALYSIS_RESULT_STATUSES:
            raise ValueError("round analysis result status is invalid")
        result_json = _optional_string(payload, "result_json")
        error = _optional_string(payload, "error")
        if error is not None and len(error) > 512:
            raise ValueError("round analysis error is too long")
        input_artifact_id = _optional_string(payload, "input_artifact_id")
        input_artifact_sha256 = _optional_digest(payload, "input_artifact_sha256")
        result_artifact_id = _optional_string(payload, "result_artifact_id")
        result_artifact_sha256 = _optional_digest(payload, "result_artifact_sha256")
        created_at = _utc_datetime(payload, "created_at")
        started_at = _optional_utc_datetime(payload, "started_at")
        completed_at = _optional_utc_datetime(payload, "completed_at")

        if state == "complete":
            if (
                result_status is None
                or result_json is None
                or error is not None
                or completed_at is None
                or completed != total
                or input_artifact_id is None
                or input_artifact_sha256 is None
                or result_artifact_id is None
                or result_artifact_sha256 is None
            ):
                raise ValueError("a complete analysis state is incomplete")
        elif state == "failed":
            if (
                error is None
                or result_status is not None
                or result_json is not None
                or completed_at is None
            ):
                raise ValueError("a failed analysis state is incomplete")
            if result_artifact_id is not None or result_artifact_sha256 is not None:
                raise ValueError("a failed analysis cannot reference a result artifact")
        elif (
            result_status is not None
            or result_json is not None
            or error is not None
            or completed_at is not None
            or result_artifact_id is not None
            or result_artifact_sha256 is not None
            or input_artifact_id is not None
            or input_artifact_sha256 is not None
        ):
            raise ValueError("a non-terminal analysis state has terminal fields")

        analysis = StoredRoundAnalysis(
            analysis_id=analysis_id,
            recording_id=request.recording_id,
            round_id=request.round_id,
            session_id=session_id,
            request_json=request_json,
            request_sha256=str(payload["request_sha256"]),
            state=state,
            total_evidence_packages=total,
            completed_evidence_packages=completed,
            result_status=result_status,
            result_json=result_json,
            error=error,
            input_artifact_id=input_artifact_id,
            input_artifact_sha256=input_artifact_sha256,
            result_artifact_id=result_artifact_id,
            result_artifact_sha256=result_artifact_sha256,
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
        )
        if state == "complete" and validate_artifacts:
            self._validate_complete_artifacts(analysis, directory)
        return analysis

    def _validate_complete_artifacts(
        self,
        analysis: StoredRoundAnalysis,
        directory: Path,
    ) -> None:
        expected_input = f"round-analyses/{analysis.analysis_id}/input.json"
        expected_result = f"round-analyses/{analysis.analysis_id}/result.json"
        if (
            analysis.input_artifact_id != expected_input
            or analysis.result_artifact_id != expected_result
        ):
            raise ValueError("round analysis artifact paths are invalid")
        assert analysis.input_artifact_sha256 is not None
        assert analysis.result_artifact_sha256 is not None
        input_bytes = _read_verified_artifact(
            directory / "input.json", analysis.input_artifact_sha256
        )
        result_bytes = _read_verified_artifact(
            directory / "result.json", analysis.result_artifact_sha256
        )
        try:
            json.loads(input_bytes.decode("utf-8"))
            json.loads(result_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("round analysis artifacts are not valid JSON") from error
        if analysis.result_json != result_bytes.decode("utf-8"):
            raise ValueError("round analysis result state differs from result.json")

    @staticmethod
    def _log_invalid(path: Path, error: BaseException) -> None:
        LOGGER.warning("invalid round-analysis resource path=%s reason=%s", path, error)


def _state_payload(analysis: StoredRoundAnalysis) -> dict[str, Any]:
    return {
        "schema_version": ROUND_ANALYSIS_STATE_SCHEMA_VERSION,
        "analysis_id": str(analysis.analysis_id),
        "recording_id": analysis.recording_id,
        "round_id": analysis.round_id,
        "session_id": str(analysis.session_id),
        "request_json": analysis.request_json,
        "request_sha256": analysis.request_sha256,
        "state": analysis.state,
        "total_evidence_packages": analysis.total_evidence_packages,
        "completed_evidence_packages": analysis.completed_evidence_packages,
        "result_status": analysis.result_status,
        "result_json": analysis.result_json,
        "error": analysis.error,
        "input_artifact_id": analysis.input_artifact_id,
        "input_artifact_sha256": analysis.input_artifact_sha256,
        "result_artifact_id": analysis.result_artifact_id,
        "result_artifact_sha256": analysis.result_artifact_sha256,
        "created_at": _utc_datetime_value(analysis.created_at),
        "started_at": _optional_utc_datetime_value(analysis.started_at),
        "completed_at": _optional_utc_datetime_value(analysis.completed_at),
    }


def _same_request(left: StoredRoundAnalysis, right: StoredRoundAnalysis) -> bool:
    return (
        left.request_sha256 == right.request_sha256
        and left.request_json == right.request_json
    )


def _string(payload: dict[str, Any], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_string(payload: dict[str, Any], name: str) -> str | None:
    value = payload[name]
    if value is not None and (not isinstance(value, str) or not value):
        raise ValueError(f"{name} must be a non-empty string or null")
    return value


def _non_negative_int(payload: dict[str, Any], name: str) -> int:
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _optional_digest(payload: dict[str, Any], name: str) -> str | None:
    value = _optional_string(payload, name)
    if value is not None and (
        len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _utc_datetime(payload: dict[str, Any], name: str) -> datetime:
    value = _string(payload, name)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO timestamp") from error
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset().total_seconds() != 0
    ):
        raise ValueError(f"{name} must use UTC")
    return parsed.astimezone(timezone.utc)


def _optional_utc_datetime(payload: dict[str, Any], name: str) -> datetime | None:
    if payload[name] is None:
        return None
    return _utc_datetime(payload, name)


def _utc_datetime_value(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("analysis timestamps must include a UTC offset")
    return value.astimezone(timezone.utc).isoformat()


def _optional_utc_datetime_value(value: datetime | None) -> str | None:
    return None if value is None else _utc_datetime_value(value)


def _read_verified_artifact(path: Path, expected_sha256: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise OSError(f"round analysis artifact is unavailable: {path.name}")
    value = path.read_bytes()
    if hashlib.sha256(value).hexdigest() != expected_sha256:
        raise OSError(f"round analysis artifact failed verification: {path.name}")
    return value


__all__ = [
    "ROUND_ANALYSIS_STATE_SCHEMA_VERSION",
    "RoundAnalysisConflict",
    "RoundAnalysisInsert",
    "RoundAnalysisNotFound",
    "RoundAnalysisStore",
    "RoundAnalysisStoreError",
]
