"""Durable ordered active-job index maintained by Job Manager transitions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from dokodetector_backend.job_models import Job, JobStorageError
from dokodetector_backend.recording_state_contract import JobProjectionAuthority

_SCHEMA = "job-recording-index/v1"
_ACTIVE = {"queued", "running", "cancelling"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class JobProjectionIndexStore:
    """Publish compact job rows and per-recording generations with the job journal."""

    def __init__(self, jobs_root: Path) -> None:
        self.root = Path(jobs_root) / "recording-projections"
        self.path = self.root / "active-jobs.sqlite3"
        self._initialized = False

    def initialize(
        self,
        authority: JobProjectionAuthority,
        *,
        legacy_intents_exist: bool,
    ) -> None:
        if self._initialized:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        try:
            with closing(self._connect(create=True)) as connection:
                objects = {
                    (kind, name)
                    for kind, name in connection.execute(
                        "SELECT type, name FROM sqlite_master WHERE type IN ('table', 'index')"
                    )
                }
                required_objects = {
                    ("table", "index_state"),
                    ("table", "recording_state"),
                    ("table", "active_jobs"),
                    ("index", "active_jobs_page_order"),
                }
                stored_state = None
                if ("table", "index_state") in objects:
                    stored_state = connection.execute(
                        "SELECT schema_version, manager_id, epoch "
                        "FROM index_state WHERE singleton = 1"
                    ).fetchone()
                if existed and stored_state is not None and not required_objects <= objects:
                    raise JobStorageError("job recording index schema is incomplete")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS index_state (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        schema_version TEXT NOT NULL,
                        manager_id TEXT NOT NULL,
                        epoch TEXT NOT NULL,
                        global_sequence INTEGER NOT NULL CHECK (global_sequence >= 1),
                        ready INTEGER NOT NULL CHECK (ready IN (0, 1))
                    );
                    CREATE TABLE IF NOT EXISTS recording_state (
                        recording_id TEXT PRIMARY KEY,
                        sequence INTEGER NOT NULL CHECK (sequence >= 0),
                        active_count INTEGER CHECK (active_count IS NULL OR active_count >= 0)
                    );
                    CREATE TABLE IF NOT EXISTS active_jobs (
                        recording_id TEXT NOT NULL,
                        job_id TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'cancelling')),
                        request_id TEXT,
                        job_sha256 TEXT NOT NULL,
                        PRIMARY KEY (recording_id, job_id)
                    ) WITHOUT ROWID;
                    CREATE INDEX IF NOT EXISTS active_jobs_page_order
                        ON active_jobs (recording_id, updated_at DESC, job_id DESC);
                    """
                )
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT schema_version, manager_id, epoch FROM index_state WHERE singleton = 1"
                ).fetchone()
                if row is None:
                    if existed and (
                        legacy_intents_exist
                        or authority.sequence != 1
                        or connection.execute("SELECT 1 FROM active_jobs LIMIT 1").fetchone()
                        or connection.execute("SELECT 1 FROM recording_state LIMIT 1").fetchone()
                    ):
                        raise JobStorageError("job recording index authority is missing")
                    connection.execute(
                        "INSERT INTO index_state VALUES (1, ?, ?, ?, ?, ?)",
                        (
                            _SCHEMA,
                            authority.manager_id,
                            authority.epoch,
                            authority.sequence,
                            int(
                                not existed and not legacy_intents_exist and authority.sequence == 1
                            ),
                        ),
                    )
                elif row != (_SCHEMA, authority.manager_id, authority.epoch):
                    raise JobStorageError("job recording index authority is corrupt")
                connection.commit()
                self._check_integrity(connection)
            self.path.chmod(0o600)
            self._initialized = True
        except JobStorageError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError) as error:
            raise JobStorageError("job recording index is missing or corrupt") from error

    def prepare_transition(
        self,
        old_job: Job | None,
        new_job: Job,
        old_authority: JobProjectionAuthority,
        new_authority: JobProjectionAuthority,
        old_job_sha256: str | None,
    ) -> list[dict[str, Any]]:
        """Validate current rows and freeze exact index deltas into the job journal."""
        try:
            if (
                old_authority.manager_id != new_authority.manager_id
                or old_authority.epoch != new_authority.epoch
                or new_authority.sequence != old_authority.sequence + 1
            ):
                raise JobStorageError("job projection authority transition is invalid")
            with closing(self._connect()) as connection:
                state = self._state(connection)
                self._check_state_authority(state, old_authority)
                if state["global_sequence"] != old_authority.sequence:
                    raise JobStorageError("job recording index sequence conflicts with authority")
                old_recording = self._recording_id(old_job)
                new_recording = self._recording_id(new_job)
                if old_job is not None and old_recording != new_recording:
                    raise JobStorageError("job recording identity cannot change")
                deltas = []
                for recording_id in sorted(
                    {value for value in (old_recording, new_recording) if value}
                ):
                    sequence_row = connection.execute(
                        "SELECT sequence, active_count FROM recording_state WHERE recording_id = ?",
                        (recording_id,),
                    ).fetchone()
                    old_sequence = 0 if sequence_row is None else sequence_row[0]
                    old_count = (
                        0
                        if sequence_row is None and state["ready"]
                        else None
                        if sequence_row is None
                        else sequence_row[1]
                    )
                    if state["ready"] and old_count is None:
                        raise JobStorageError("recording active count is missing")
                    old_item = (
                        self._index_item(old_job, old_job_sha256)
                        if old_recording == recording_id
                        else None
                    )
                    new_item = (
                        self._index_item(new_job, _digest(new_job.model_dump(mode="json")))
                        if new_recording == recording_id
                        else None
                    )
                    new_count = self._next_count(old_count, old_item, new_item)
                    if new_count is not None and new_count < 0:
                        raise JobStorageError("recording active count conflicts with job state")
                    if state["ready"]:
                        self._validate_current_item(
                            connection,
                            recording_id,
                            old_job.id if old_job else new_job.id,
                            old_item,
                        )
                    deltas.append(
                        {
                            "recording_id": recording_id,
                            "job_id": new_job.id,
                            "old_sequence": old_sequence,
                            "new_sequence": old_sequence + 1,
                            "old_count": old_count,
                            "new_count": new_count,
                            "old_item": old_item,
                            "new_item": new_item,
                        }
                    )
                return deltas
        except JobStorageError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError, TypeError) as error:
            raise JobStorageError("job recording index cannot prepare transition") from error

    def apply_transition(self, record: dict[str, Any]) -> None:
        """Apply or replay the journaled index delta in one SQLite transaction."""
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                state = self._state(connection)
                old_authority = JobProjectionAuthority.model_validate(record["old_authority"])
                new_authority = JobProjectionAuthority.model_validate(record["new_authority"])
                self._check_state_authority(state, old_authority)
                if state["global_sequence"] == new_authority.sequence:
                    self._validate_new_state(connection, state, record["index_deltas"])
                    connection.commit()
                    return
                if state["global_sequence"] != old_authority.sequence:
                    raise JobStorageError("job recording index sequence conflicts with transition")

                for delta in record["index_deltas"]:
                    self._apply_delta(connection, state, delta)
                connection.execute(
                    "UPDATE index_state SET global_sequence = ? WHERE singleton = 1",
                    (new_authority.sequence,),
                )
                connection.commit()
        except JobStorageError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise JobStorageError("job recording index transition failed") from error

    def validate_authority(self, authority: JobProjectionAuthority) -> None:
        try:
            with closing(self._connect()) as connection:
                state = self._state(connection)
                self._check_state_authority(state, authority)
                if state["global_sequence"] != authority.sequence:
                    raise JobStorageError("job recording index sequence conflicts with authority")
        except JobStorageError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError, TypeError) as error:
            raise JobStorageError("job recording index is corrupt") from error

    def validate_transition_authority(
        self,
        old_authority: JobProjectionAuthority,
        new_authority: JobProjectionAuthority,
        *,
        manager_authority: JobProjectionAuthority,
    ) -> None:
        """Allow only the prepared transaction's old or new index generation."""
        try:
            with closing(self._connect()) as connection:
                state = self._state(connection)
                self._check_state_authority(state, old_authority)
                allowed = {old_authority.sequence, new_authority.sequence}
                if manager_authority.sequence == new_authority.sequence:
                    allowed = {new_authority.sequence}
                if state["global_sequence"] not in allowed:
                    raise JobStorageError("job recording index conflicts with prepared transition")
        except JobStorageError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError, TypeError) as error:
            raise JobStorageError("job recording index is corrupt") from error

    def state(
        self, authority: JobProjectionAuthority, recording_id: str | None = None
    ) -> dict[str, Any]:
        """Return current index readiness and a recording generation without scanning jobs."""
        with closing(self._connect()) as connection:
            state = self._state(connection)
            self._check_state_authority(state, authority)
            if state["global_sequence"] != authority.sequence:
                raise JobStorageError("job recording index sequence conflicts with authority")
            result = {"ready": bool(state["ready"]), "global_sequence": state["global_sequence"]}
            if recording_id is not None:
                row = connection.execute(
                    "SELECT sequence, active_count FROM recording_state WHERE recording_id = ?",
                    (recording_id,),
                ).fetchone()
                result["recording_sequence"] = 0 if row is None else row[0]
                result["active_count"] = 0 if row is None else row[1]
            return result

    def _apply_delta(
        self, connection: sqlite3.Connection, state: dict[str, Any], delta: dict[str, Any]
    ) -> None:
        recording_id = delta["recording_id"]
        sequence_row = connection.execute(
            "SELECT sequence, active_count FROM recording_state WHERE recording_id = ?",
            (recording_id,),
        ).fetchone()
        current_sequence = 0 if sequence_row is None else sequence_row[0]
        if current_sequence != delta["old_sequence"]:
            raise JobStorageError("recording index sequence conflicts with transition")
        current_count = (
            0
            if sequence_row is None and state["ready"]
            else None
            if sequence_row is None
            else sequence_row[1]
        )
        if current_count != delta["old_count"]:
            raise JobStorageError("recording active count conflicts with transition")
        if state["ready"] and current_count is None:
            raise JobStorageError("recording active count is missing")
        if state["ready"]:
            self._validate_current_item(
                connection,
                recording_id,
                delta["job_id"],
                delta["old_item"],
            )
        self._write_item(connection, recording_id, delta["job_id"], delta["new_item"])
        connection.execute(
            "INSERT INTO recording_state(recording_id, sequence, active_count) VALUES (?, ?, ?) "
            "ON CONFLICT(recording_id) DO UPDATE SET sequence = excluded.sequence, "
            "active_count = excluded.active_count",
            (recording_id, delta["new_sequence"], delta["new_count"]),
        )

    def _validate_new_state(
        self,
        connection: sqlite3.Connection,
        state: dict[str, Any],
        deltas: list[dict[str, Any]],
    ) -> None:
        for delta in deltas:
            sequence = connection.execute(
                "SELECT sequence, active_count FROM recording_state WHERE recording_id = ?",
                (delta["recording_id"],),
            ).fetchone()
            if (
                sequence is None
                or sequence[0] != delta["new_sequence"]
                or sequence[1] != delta["new_count"]
            ):
                raise JobStorageError(
                    "recording index sequence conflicts with committed transition"
                )
            if state["ready"]:
                if delta["new_count"] is None:
                    raise JobStorageError("recording active count is missing")
                self._validate_current_item(
                    connection,
                    delta["recording_id"],
                    delta["job_id"],
                    delta["new_item"],
                )

    @staticmethod
    def _validate_current_item(
        connection: sqlite3.Connection,
        recording_id: str,
        job_id: str,
        expected: dict[str, Any] | None,
    ) -> None:
        row = connection.execute(
            "SELECT updated_at, status, request_id, job_sha256 FROM active_jobs "
            "WHERE recording_id = ? AND job_id = ?",
            (recording_id, job_id),
        ).fetchone()
        actual = (
            None
            if row is None
            else dict(zip(("updated_at", "status", "request_id", "job_sha256"), row, strict=True))
        )
        wanted = (
            None
            if expected is None
            else {
                "updated_at": expected["updated_at"],
                "status": expected["status"],
                "request_id": expected["request_id"],
                "job_sha256": expected["job_sha256"],
            }
        )
        if actual != wanted:
            raise JobStorageError("active job index row conflicts with job transition")

    @staticmethod
    def _write_item(
        connection: sqlite3.Connection,
        recording_id: str,
        job_id: str,
        item: dict[str, Any] | None,
    ) -> None:
        if item is None:
            connection.execute(
                "DELETE FROM active_jobs WHERE recording_id = ? AND job_id = ?",
                (recording_id, job_id),
            )
            return
        connection.execute(
            "INSERT INTO active_jobs("
            "recording_id, job_id, updated_at, status, request_id, job_sha256) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(recording_id, job_id) DO UPDATE SET "
            "updated_at = excluded.updated_at, status = excluded.status, "
            "request_id = excluded.request_id, job_sha256 = excluded.job_sha256",
            (
                recording_id,
                item["job_id"],
                item["updated_at"],
                item["status"],
                item["request_id"],
                item["job_sha256"],
            ),
        )

    @staticmethod
    def _next_count(
        current: int | None,
        old_item: dict[str, Any] | None,
        new_item: dict[str, Any] | None,
    ) -> int | None:
        if current is None:
            return None
        return current - int(old_item is not None) + int(new_item is not None)

    @staticmethod
    def _recording_id(job: Job | None) -> str | None:
        if job is None:
            return None
        value = job.context.get("recording_id")
        return value if isinstance(value, str) and value else None

    @classmethod
    def _index_item(cls, job: Job | None, job_sha256: str | None) -> dict[str, Any] | None:
        if job is None or job.state not in _ACTIVE:
            return None
        recording_id = cls._recording_id(job)
        if recording_id is None or job_sha256 is None:
            return None
        return {
            "job_id": job.id,
            "updated_at": job.updated_at,
            "status": job.state,
            "request_id": job.correlation_id,
            "job_sha256": job_sha256,
        }

    @staticmethod
    def _check_state_authority(state: dict[str, Any], authority: JobProjectionAuthority) -> None:
        if (
            state["schema_version"] != _SCHEMA
            or state["manager_id"] != authority.manager_id
            or state["epoch"] != authority.epoch
        ):
            raise JobStorageError("job recording index authority is corrupt")

    @staticmethod
    def _state(connection: sqlite3.Connection) -> dict[str, Any]:
        row = connection.execute(
            "SELECT schema_version, manager_id, epoch, global_sequence, ready "
            "FROM index_state WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise JobStorageError("job recording index state is missing")
        return dict(
            zip(
                ("schema_version", "manager_id", "epoch", "global_sequence", "ready"),
                row,
                strict=True,
            )
        )

    def _connect(self, *, create: bool = False) -> sqlite3.Connection:
        if not create and not self.path.is_file():
            raise JobStorageError("job recording index is missing")
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        if create:
            connection.execute("PRAGMA journal_mode = DELETE")
        return connection

    @staticmethod
    def _check_integrity(connection: sqlite3.Connection) -> None:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if result != ("ok",):
            raise JobStorageError("job recording index integrity check failed")
