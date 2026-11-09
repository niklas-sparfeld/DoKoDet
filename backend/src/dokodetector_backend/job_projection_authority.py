"""Durable authority and recovery for compact job projections."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from dokodetector_backend.filesystem import _sync_directory, atomic_replace_json
from dokodetector_backend.job_models import Job, JobStorageError
from dokodetector_backend.recording_state_contract import JobProjectionAuthority


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class JobProjectionAuthorityStore:
    """Advance one durable authority with every durable job-record replacement."""

    def __init__(self, root: Path, after_write: Callable[[str], None]) -> None:
        self.root = root
        self.authority_path = root / "recording-projections" / "authority.json"
        self.transition_path = root / "recording-projections" / "job-transition.json"
        self.after_write = after_write

    def initialize(self) -> None:
        self.authority_path.parent.mkdir(parents=True, exist_ok=True)
        if self.authority_path.exists():
            self._read_authority()
            self.recover_transition()
            return
        authority = JobProjectionAuthority(manager_id=str(uuid4()), epoch=str(uuid4()), sequence=1)
        atomic_replace_json(self.authority_path, authority.model_dump(mode="json"))

    def authority(self) -> JobProjectionAuthority:
        self.recover_transition()
        return self._read_authority()

    def publish(self, job: Job) -> None:
        self.initialize()
        self.recover_transition()
        path = self.root / job.id / "job.json"
        old_payload = path.read_bytes() if path.exists() else None
        old_digest = None if old_payload is None else _sha256(old_payload)
        next_payload = _canonical(job.model_dump(mode="json"))
        next_digest = _sha256(next_payload)
        authority = self._read_authority()
        next_authority = authority.model_copy(update={"sequence": authority.sequence + 1})
        record = {
            "schema_version": "job-record-transition/v1",
            "job_id": job.id,
            "old_job_sha256": old_digest,
            "new_job_sha256": next_digest,
            "new_job": json.loads(next_payload),
            "old_authority": authority.model_dump(mode="json"),
            "new_authority": next_authority.model_dump(mode="json"),
        }
        atomic_replace_json(self.transition_path, record)
        self.after_write("job_transition_prepared")
        self._finish_transition(record)

    def recover_transition(self) -> None:
        if not self.transition_path.exists():
            return
        try:
            record = json.loads(self.transition_path.read_bytes())
            self._validate_transition(record)
            self._finish_transition(record)
        except JobStorageError:
            raise
        except (OSError, TypeError, ValueError, KeyError) as error:
            raise JobStorageError("invalid prepared job transition") from error

    def _finish_transition(self, record: dict[str, Any]) -> None:
        job_id = record["job_id"]
        path = self.root / job_id / "job.json"
        current = path.read_bytes() if path.exists() else None
        current_digest = None if current is None else _sha256(current)
        old_digest = record["old_job_sha256"]
        new_payload = _canonical(record["new_job"])
        new_digest = record["new_job_sha256"]
        job_is_old = current_digest == old_digest
        job_is_new = current_digest == new_digest
        if not job_is_old and not job_is_new:
            raise JobStorageError("job record conflicts with prepared transition")

        authority = self._read_authority()
        old_authority = JobProjectionAuthority.model_validate(record["old_authority"])
        new_authority = JobProjectionAuthority.model_validate(record["new_authority"])
        authority_is_old = authority == old_authority
        authority_is_new = authority == new_authority
        if not authority_is_old and not authority_is_new:
            raise JobStorageError("job authority conflicts with prepared transition")
        if job_is_old and authority_is_new:
            raise JobStorageError("job authority advanced before its job record")

        if job_is_old:
            atomic_replace_json(path, new_payload)
            self.after_write("job_transition_record")
        if authority_is_old:
            atomic_replace_json(self.authority_path, new_authority.model_dump(mode="json"))
            self.after_write("job_transition_authority")

        self.transition_path.unlink(missing_ok=True)
        _sync_directory(self.transition_path.parent)
        self.after_write("job_transition_committed")

    def _read_authority(self) -> JobProjectionAuthority:
        try:
            return JobProjectionAuthority.model_validate_json(self.authority_path.read_bytes())
        except (OSError, ValueError, TypeError) as error:
            raise JobStorageError("job projection authority is missing or corrupt") from error

    @staticmethod
    def _validate_transition(record: Any) -> None:
        if not isinstance(record, dict) or set(record) != {
            "schema_version",
            "job_id",
            "old_job_sha256",
            "new_job_sha256",
            "new_job",
            "old_authority",
            "new_authority",
        }:
            raise ValueError("transition fields are invalid")
        if record["schema_version"] != "job-record-transition/v1":
            raise ValueError("transition version is invalid")
        job = Job.model_validate(record["new_job"])
        if job.id != record["job_id"]:
            raise ValueError("transition job identity is invalid")
        if _sha256(_canonical(record["new_job"])) != record["new_job_sha256"]:
            raise ValueError("transition job digest is invalid")
        old_authority = JobProjectionAuthority.model_validate(record["old_authority"])
        new_authority = JobProjectionAuthority.model_validate(record["new_authority"])
        if (
            old_authority.manager_id != new_authority.manager_id
            or old_authority.epoch != new_authority.epoch
            or new_authority.sequence != old_authority.sequence + 1
        ):
            raise ValueError("transition authority sequence is invalid")
        if record["old_job_sha256"] is not None and (
            not isinstance(record["old_job_sha256"], str) or len(record["old_job_sha256"]) != 64
        ):
            raise ValueError("prior job digest is invalid")
