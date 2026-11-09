"""Durable ordered active-job index maintained by Job Manager transitions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from dokodetector_backend.job_models import (
    _TERMINAL,
    Intent,
    Job,
    JobStorageError,
    Queue,
    QueueGroup,
)
from dokodetector_backend.recording_state_contract import JobProjectionAuthority

_SCHEMA = "job-recording-index/v1"
_ACTIVE = {"queued", "running", "cancelling"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class JobProjectionIndexStore:
    """Publish compact job rows and per-recording generations with the job journal."""

    def __init__(self, jobs_root: Path) -> None:
        self.root = Path(jobs_root) / "recording-projections"
        self.path = self.root / "active-jobs.sqlite3"
        self._initialized = False
        self._needs_legacy_queue_import = False

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
                queue_objects = {
                    (kind, name)
                    for kind, name in connection.execute(
                        "SELECT type, name FROM sqlite_master WHERE type IN ('table', 'index')"
                    )
                }
                required_queue_objects = {
                    ("table", "queue_state"),
                    ("table", "queue_groups"),
                    ("table", "queue_children"),
                    ("table", "parent_children"),
                    ("index", "queue_group_order"),
                    ("index", "queue_child_order"),
                }
                stored_state = None
                if ("table", "index_state") in objects:
                    stored_state = connection.execute(
                        "SELECT schema_version, manager_id, epoch "
                        "FROM index_state WHERE singleton = 1"
                    ).fetchone()
                if existed and stored_state is not None and not required_objects <= objects:
                    raise JobStorageError("job recording index schema is incomplete")
                if ("table", "queue_state") in queue_objects and not (
                    required_queue_objects <= queue_objects
                    or not (
                        ("index", "parent_children_dependency") in queue_objects
                        or ("index", "parent_children_pending_dependency") in queue_objects
                    )
                ):
                    raise JobStorageError("job queue authority schema is incomplete")
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
                    CREATE TABLE IF NOT EXISTS queue_state (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        revision INTEGER NOT NULL CHECK (revision >= 0),
                        ready INTEGER NOT NULL CHECK (ready IN (0, 1))
                    );
                    CREATE TABLE IF NOT EXISTS queue_groups (
                        group_id TEXT PRIMARY KEY,
                        position INTEGER NOT NULL UNIQUE CHECK (position >= 0)
                    );
                    CREATE TABLE IF NOT EXISTS queue_children (
                        parent_id TEXT NOT NULL REFERENCES queue_groups(group_id) ON DELETE CASCADE,
                        child_id TEXT NOT NULL,
                        sequence INTEGER NOT NULL CHECK (sequence >= 1),
                        PRIMARY KEY (parent_id, child_id),
                        UNIQUE (parent_id, sequence)
                    ) WITHOUT ROWID;
                    CREATE INDEX IF NOT EXISTS queue_group_order ON queue_groups(position);
                    CREATE INDEX IF NOT EXISTS queue_child_order
                        ON queue_children(parent_id, sequence);
                    CREATE TABLE IF NOT EXISTS parent_children (
                        parent_id TEXT NOT NULL,
                        child_id TEXT PRIMARY KEY,
                        sequence INTEGER NOT NULL CHECK (sequence >= 1),
                        state TEXT NOT NULL,
                        UNIQUE (parent_id, sequence)
                    ) WITHOUT ROWID;
                    CREATE INDEX IF NOT EXISTS parent_children_pending_dependency
                        ON parent_children(parent_id, sequence) WHERE state != 'succeeded';
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
                queue_state = connection.execute(
                    "SELECT revision, ready FROM queue_state WHERE singleton = 1"
                ).fetchone()
                if queue_state is None:
                    self._needs_legacy_queue_import = True
                    connection.execute(
                        "INSERT INTO queue_state VALUES (1, 0, ?)",
                        (
                            int(
                                not existed and not legacy_intents_exist and authority.sequence == 1
                            ),
                        ),
                    )
                connection.commit()
                connection.execute("DROP INDEX IF EXISTS parent_children_dependency")
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
                    self._validate_queue_delta(connection, record["queue_delta"], new=True)
                    connection.commit()
                    return
                if state["global_sequence"] != old_authority.sequence:
                    raise JobStorageError("job recording index sequence conflicts with transition")

                for delta in record["index_deltas"]:
                    self._apply_delta(connection, state, delta)
                self._apply_queue_delta(connection, record["queue_delta"])
                connection.execute(
                    "UPDATE index_state SET global_sequence = ? WHERE singleton = 1",
                    (new_authority.sequence,),
                )
                connection.commit()
        except JobStorageError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise JobStorageError("job recording index transition failed") from error

    def prepare_queue_delta(self, old_job: Job | None, new_job: Job) -> dict[str, Any]:
        """Freeze one job's exact queue membership change into its job journal."""
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT revision, ready FROM queue_state WHERE singleton = 1"
                ).fetchone()
                if row is None:
                    raise JobStorageError("job queue authority is missing")
                revision, ready = row
                if not ready:
                    return {
                        "ready": False,
                        "old_revision": revision,
                        "new_revision": revision,
                        "old_group": None,
                        "new_group": None,
                        "old_child": None,
                        "new_child": None,
                        "old_parent_child": None,
                        "new_parent_child": None,
                    }
                job_id = new_job.id
                group_row = connection.execute(
                    "SELECT position FROM queue_groups WHERE group_id = ?", (job_id,)
                ).fetchone()
                old_group = (
                    None if group_row is None else {"group_id": job_id, "position": group_row[0]}
                )
                old_child_row = connection.execute(
                    "SELECT parent_id, sequence FROM queue_children WHERE child_id = ?",
                    (job_id,),
                ).fetchone()
                old_child = (
                    None
                    if old_child_row is None
                    else {
                        "parent_id": old_child_row[0],
                        "child_id": job_id,
                        "sequence": old_child_row[1],
                    }
                )
                parent_child_row = connection.execute(
                    "SELECT parent_id, sequence, state FROM parent_children WHERE child_id = ?",
                    (job_id,),
                ).fetchone()
                old_parent_child = (
                    None
                    if parent_child_row is None
                    else {
                        "parent_id": parent_child_row[0],
                        "child_id": job_id,
                        "sequence": parent_child_row[1],
                        "state": parent_child_row[2],
                    }
                )
                expected_old_group = self._queue_group_eligible(old_job)
                expected_old_child = self._queue_child_eligible(old_job)
                if old_job is None:
                    if old_group is not None or old_child is not None:
                        raise JobStorageError("unexpected queue membership for new job")
                elif expected_old_group != (old_group is not None):
                    raise JobStorageError("queue group conflicts with job state")
                elif (old_job.parent_id if expected_old_child else None) != (
                    None if old_child is None else old_child["parent_id"]
                ):
                    raise JobStorageError("queue child conflicts with job state")
                if old_job is None:
                    if old_parent_child is not None:
                        raise JobStorageError("unexpected parent-child authority for new job")
                elif old_job.parent_id is None:
                    if old_parent_child is not None:
                        raise JobStorageError("root job has parent-child authority")
                elif old_parent_child is None or (
                    old_parent_child["parent_id"] != old_job.parent_id
                    or old_parent_child["state"] != old_job.state
                ):
                    raise JobStorageError("parent-child authority conflicts with job state")

                new_group = None
                if self._queue_group_eligible(new_job):
                    if old_group is not None:
                        if (
                            old_job is not None
                            and old_job.type == "automated_pipeline"
                            and old_job.state == "waiting"
                            and new_job.state == "queued"
                        ):
                            last = connection.execute(
                                "SELECT position FROM queue_groups ORDER BY position DESC LIMIT 1"
                            ).fetchone()
                            new_group = {
                                "group_id": job_id,
                                "position": 0 if last is None else last[0] + 1,
                            }
                        else:
                            new_group = old_group
                    else:
                        last = connection.execute(
                            "SELECT position FROM queue_groups ORDER BY position DESC LIMIT 1"
                        ).fetchone()
                        new_group = {
                            "group_id": job_id,
                            "position": 0 if last is None else last[0] + 1,
                        }

                new_child = None
                if self._queue_child_eligible(new_job):
                    parent_id = new_job.parent_id
                    if not connection.execute(
                        "SELECT 1 FROM queue_groups WHERE group_id = ?", (parent_id,)
                    ).fetchone():
                        raise JobStorageError("parent queue group is missing")
                    if old_child is not None:
                        new_child = old_child
                    else:
                        intent_path = self.root.parent / "intents" / f"{job_id}.json"
                        intent = Intent.model_validate_json(intent_path.read_bytes())
                        if intent.job.id != job_id:
                            raise JobStorageError("queue intent identity conflicts with job")
                        new_child = {
                            "parent_id": parent_id,
                            "child_id": job_id,
                            "sequence": intent.sequence,
                        }

                new_parent_child = None
                if new_job.parent_id is not None:
                    if old_parent_child is not None:
                        sequence = old_parent_child["sequence"]
                    else:
                        intent = Intent.model_validate_json(
                            (self.root.parent / "intents" / f"{job_id}.json").read_bytes()
                        )
                        if intent.job.id != job_id:
                            raise JobStorageError("parent-child intent identity conflicts with job")
                        sequence = intent.sequence
                    new_parent_child = {
                        "parent_id": new_job.parent_id,
                        "child_id": job_id,
                        "sequence": sequence,
                        "state": new_job.state,
                    }

                changed = old_group != new_group or old_child != new_child
                return {
                    "ready": True,
                    "old_revision": revision,
                    "new_revision": revision + int(changed),
                    "old_group": old_group,
                    "new_group": new_group,
                    "old_child": old_child,
                    "new_child": new_child,
                    "old_parent_child": old_parent_child,
                    "new_parent_child": new_parent_child,
                }
        except JobStorageError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise JobStorageError("job queue cannot prepare transition") from error

    @staticmethod
    def _queue_group_eligible(job: Job | None) -> bool:
        if job is None or job.parent_id is not None:
            return False
        if job.type == "automated_pipeline":
            return job.state not in _TERMINAL
        return job.state == "queued"

    @staticmethod
    def _queue_child_eligible(job: Job | None) -> bool:
        return job is not None and job.parent_id is not None and job.state == "queued"

    @staticmethod
    def _apply_queue_delta(connection: sqlite3.Connection, delta: dict[str, Any]) -> None:
        state = connection.execute(
            "SELECT revision, ready FROM queue_state WHERE singleton = 1"
        ).fetchone()
        if state is None or state[1] != int(delta["ready"]):
            raise JobStorageError("queue readiness conflicts with transition")
        if state[0] == delta["new_revision"] and delta["new_revision"] != delta["old_revision"]:
            JobProjectionIndexStore._validate_queue_delta(connection, delta, new=True)
            return
        if state[0] != delta["old_revision"]:
            raise JobStorageError("queue revision conflicts with transition")
        JobProjectionIndexStore._validate_queue_delta(connection, delta, new=False)
        if delta["old_parent_child"] != delta["new_parent_child"]:
            item = delta["old_parent_child"]
            if item is not None:
                connection.execute(
                    "DELETE FROM parent_children WHERE child_id = ?", (item["child_id"],)
                )
        if delta["old_child"] != delta["new_child"]:
            item = delta["old_child"]
            if item is not None:
                connection.execute(
                    "DELETE FROM queue_children WHERE child_id = ?", (item["child_id"],)
                )
        if delta["old_group"] != delta["new_group"]:
            item = delta["old_group"]
            if item is not None:
                connection.execute(
                    "DELETE FROM queue_groups WHERE group_id = ?", (item["group_id"],)
                )
        group = delta["new_group"]
        if group is not None and delta["old_group"] != group:
            connection.execute(
                "INSERT INTO queue_groups(group_id, position) VALUES (?, ?)",
                (group["group_id"], group["position"]),
            )
        child = delta["new_child"]
        if child is not None and delta["old_child"] != child:
            connection.execute(
                "INSERT INTO queue_children(parent_id, child_id, sequence) VALUES (?, ?, ?)",
                (child["parent_id"], child["child_id"], child["sequence"]),
            )
        parent_child = delta["new_parent_child"]
        if parent_child is not None and delta["old_parent_child"] != parent_child:
            connection.execute(
                "INSERT INTO parent_children(parent_id, child_id, sequence, state) "
                "VALUES (?, ?, ?, ?)",
                (
                    parent_child["parent_id"],
                    parent_child["child_id"],
                    parent_child["sequence"],
                    parent_child["state"],
                ),
            )
        connection.execute(
            "UPDATE queue_state SET revision = ? WHERE singleton = 1",
            (delta["new_revision"],),
        )

    @staticmethod
    def _validate_queue_delta(
        connection: sqlite3.Connection, delta: dict[str, Any], *, new: bool
    ) -> None:
        suffix = "new" if new else "old"
        group = delta[f"{suffix}_group"]
        child = delta[f"{suffix}_child"]
        parent_child = delta[f"{suffix}_parent_child"]
        if group is not None:
            row = connection.execute(
                "SELECT position FROM queue_groups WHERE group_id = ?", (group["group_id"],)
            ).fetchone()
            if row != (group["position"],):
                raise JobStorageError("queue group conflicts with job transition")
        elif delta["old_group"] is not None and not new:
            row = connection.execute(
                "SELECT 1 FROM queue_groups WHERE group_id = ?",
                (delta["old_group"]["group_id"],),
            ).fetchone()
            if row is not None:
                raise JobStorageError("queue group removal conflicts with transition")
        if child is not None:
            row = connection.execute(
                "SELECT parent_id, sequence FROM queue_children WHERE child_id = ?",
                (child["child_id"],),
            ).fetchone()
            if row != (child["parent_id"], child["sequence"]):
                raise JobStorageError("queue child conflicts with job transition")
        elif delta["old_child"] is not None and not new:
            row = connection.execute(
                "SELECT 1 FROM queue_children WHERE child_id = ?",
                (delta["old_child"]["child_id"],),
            ).fetchone()
            if row is not None:
                raise JobStorageError("queue child removal conflicts with transition")
        if parent_child is not None:
            row = connection.execute(
                "SELECT parent_id, sequence, state FROM parent_children WHERE child_id = ?",
                (parent_child["child_id"],),
            ).fetchone()
            if row != (
                parent_child["parent_id"],
                parent_child["sequence"],
                parent_child["state"],
            ):
                raise JobStorageError("parent-child authority conflicts with job transition")
        elif delta["old_parent_child"] is not None and not new:
            row = connection.execute(
                "SELECT 1 FROM parent_children WHERE child_id = ?",
                (delta["old_parent_child"]["child_id"],),
            ).fetchone()
            if row is not None:
                raise JobStorageError("parent-child authority removal conflicts with transition")

    def preceding_child_not_succeeded(self, parent_id: str, sequence: int) -> bool:
        with closing(self._connect()) as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM parent_children WHERE parent_id = ? AND sequence < ? "
                    "AND state != 'succeeded' ORDER BY sequence LIMIT 1",
                    (parent_id, sequence),
                ).fetchone()
                is not None
            )

    def parent_children(self, parent_id: str, *, active_only: bool = False) -> list[str]:
        with closing(self._connect()) as connection:
            terminal = (
                " AND state NOT IN ('succeeded', 'failed', 'cancelled', 'interrupted')"
                if active_only
                else ""
            )
            return [
                row[0]
                for row in connection.execute(
                    "SELECT child_id FROM parent_children WHERE parent_id = ?"
                    + terminal
                    + " ORDER BY sequence",
                    (parent_id,),
                )
            ]

    def rebuild_parent_children(self, rows: list[tuple[str, str, int, str]]) -> None:
        """Rebuild ordered parent-child state during explicit manager startup repair."""
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM parent_children")
                connection.executemany(
                    "INSERT INTO parent_children(parent_id, child_id, sequence, state) "
                    "VALUES (?, ?, ?, ?)",
                    rows,
                )
                connection.commit()
        except (OSError, sqlite3.DatabaseError, ValueError, TypeError) as error:
            raise JobStorageError("parent-child authority rebuild failed") from error

    def parent_child_sequence(self, child_id: str) -> tuple[str, int, str] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT parent_id, sequence, state FROM parent_children WHERE child_id = ?",
                (child_id,),
            ).fetchone()
            return None if row is None else (row[0], row[1], row[2])

    def queue_first_child(self, parent_id: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT child_id FROM queue_children WHERE parent_id = ? ORDER BY sequence LIMIT 1",
                (parent_id,),
            ).fetchone()
            return None if row is None else row[0]

    def queue_group_exists(self, group_id: str) -> bool:
        with closing(self._connect()) as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM queue_groups WHERE group_id = ?", (group_id,)
                ).fetchone()
                is not None
            )

    def move_queue_group_to_end(self, group_id: str) -> None:
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT position FROM queue_groups WHERE group_id = ?", (group_id,)
                ).fetchone()
                if row is None:
                    connection.rollback()
                    return
                last = connection.execute(
                    "SELECT group_id, position FROM queue_groups ORDER BY position DESC LIMIT 1"
                ).fetchone()
                if last is not None and last[0] == group_id:
                    connection.rollback()
                    return
                revision = connection.execute(
                    "SELECT revision FROM queue_state WHERE singleton = 1"
                ).fetchone()
                if revision is None:
                    raise JobStorageError("job queue authority is missing")
                connection.execute(
                    "UPDATE queue_groups SET position = ? WHERE group_id = ?",
                    (last[1] + 1 if last is not None else 0, group_id),
                )
                connection.execute(
                    "UPDATE queue_state SET revision = ? WHERE singleton = 1",
                    (revision[0] + 1,),
                )
                connection.commit()
        except JobStorageError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError, TypeError) as error:
            raise JobStorageError("job queue reorder failed") from error

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

    def queue(self) -> Queue:
        """Read queue groups in their durable operator order."""
        try:
            with closing(self._connect()) as connection:
                queue_state = connection.execute(
                    "SELECT revision, ready FROM queue_state WHERE singleton = 1"
                ).fetchone()
                if queue_state is None:
                    raise JobStorageError("job queue authority is missing")
                groups = []
                for (group_id,) in connection.execute(
                    "SELECT group_id FROM queue_groups ORDER BY position"
                ):
                    children = [
                        row[0]
                        for row in connection.execute(
                            "SELECT child_id FROM queue_children WHERE parent_id = ? "
                            "ORDER BY sequence",
                            (group_id,),
                        )
                    ]
                    groups.append(QueueGroup(group_id=group_id, child_job_ids=children))
                return Queue(revision=queue_state[0], groups=groups)
        except JobStorageError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError, TypeError) as error:
            raise JobStorageError("job queue authority is corrupt") from error

    def replace_queue(self, queue: Queue, *, ready: bool = True) -> None:
        """Replace queue membership during explicit startup repair or operator reorder."""
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM queue_children")
                connection.execute("DELETE FROM queue_groups")
                for group_position, group in enumerate(queue.groups):
                    connection.execute(
                        "INSERT INTO queue_groups(group_id, position) VALUES (?, ?)",
                        (group.group_id, group_position),
                    )
                    for child_position, child_id in enumerate(group.child_job_ids, start=1):
                        connection.execute(
                            "INSERT INTO queue_children(parent_id, child_id, sequence) "
                            "VALUES (?, ?, ?)",
                            (group.group_id, child_id, child_position),
                        )
                connection.execute(
                    "INSERT INTO queue_state(singleton, revision, ready) VALUES (1, ?, ?) "
                    "ON CONFLICT(singleton) DO UPDATE SET revision = excluded.revision, "
                    "ready = excluded.ready",
                    (queue.revision, int(ready)),
                )
                connection.commit()
        except (OSError, sqlite3.DatabaseError, ValueError, TypeError) as error:
            raise JobStorageError("job queue authority update failed") from error

    def queue_ready(self) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT ready FROM queue_state WHERE singleton = 1").fetchone()
            if row is None:
                raise JobStorageError("job queue authority is missing")
            return bool(row[0])

    @property
    def needs_legacy_queue_import(self) -> bool:
        return self._needs_legacy_queue_import

    def mark_queue_ready(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE queue_state SET ready = 1 WHERE singleton = 1")
            connection.commit()

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
