"""Rebuildable metadata projection for recording-list reads.

Source files remain authoritative. One atomic pending record commits the source value with
its compact projection delta. The catalog applies that delta once, stores a source receipt,
and clears the pending record. Readers never inspect source directories.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import RLock
from typing import Any

from dokodetector_backend.filesystem import atomic_replace_json
from dokodetector_backend.pipeline_storage import _process_lock

_SCHEMA = "recording-catalog-index/v1"
_ACTIVE_POINTER_SCHEMA = "recording-catalog-active/v1"


class RecordingCatalogError(RuntimeError):
    """The recording catalog is not ready or its publication contract is invalid."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


class RecordingCatalogIndex:
    """Apply source-owned deltas to one versioned SQLite metadata index."""

    def __init__(self, root: Path | str, *, _database_override: Path | None = None) -> None:
        self.root = Path(root) / "recording-catalog"
        self.sources = self.root / "sources"
        self.outbox = self.root / "outbox"
        self._thread_lock = RLock()
        self._database_override = _database_override

    @property
    def path(self) -> Path:
        """Return the active generation path (or its initial path before first activation)."""
        return self._database_path(allow_initial=True)

    def _database_path(self, *, allow_initial: bool = False) -> Path:
        if self._database_override is not None:
            return self._database_override
        pointer_path = self.root / "active-catalog.json"
        if not pointer_path.exists():
            if allow_initial:
                return self.root / "generations" / "catalog-generation-00000001.sqlite3"
            raise RecordingCatalogError("catalog index is absent")
        value = self._read_required(pointer_path)
        generation = value.get("generation")
        filename = value.get("filename")
        if (
            set(value) != {"schema_version", "generation", "filename"}
            or value.get("schema_version") != _ACTIVE_POINTER_SCHEMA
            or not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 1
            or filename != f"catalog-generation-{generation:08d}.sqlite3"
        ):
            raise RecordingCatalogError("catalog active-generation pointer is corrupt")
        return self.root / "generations" / filename

    def initialize(self) -> None:
        is_staged = self._database_override is not None
        pointer_path = self.root / "active-catalog.json"
        if (
            not is_staged
            and not pointer_path.exists()
            and (self.sources.exists() or self.outbox.exists())
        ):
            raise RecordingCatalogError("catalog index is absent while source publications exist")
        self.root.mkdir(parents=True, exist_ok=True)
        database_path = self._database_path(allow_initial=True)
        existed = database_path.exists()
        if not is_staged and pointer_path.exists() and not existed:
            raise RecordingCatalogError("active catalog generation is absent")
        if not is_staged and not pointer_path.exists() and existed:
            raise RecordingCatalogError("catalog generation exists without an active pointer")
        try:
            with closing(self._connect(create=True)) as connection:
                objects = {
                    (kind, name)
                    for kind, name in connection.execute(
                        "SELECT type, name FROM sqlite_master WHERE type IN ('table', 'index')"
                    )
                }
                expected = {
                    ("table", "catalog_state"),
                    ("table", "recording_rows"),
                    ("table", "source_receipts"),
                    ("index", "recording_page_order"),
                }
                if existed and not expected <= objects:
                    raise RecordingCatalogError("catalog index schema is incomplete")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS catalog_state (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        schema_version TEXT NOT NULL,
                        generation INTEGER NOT NULL CHECK (generation >= 1),
                        ready INTEGER NOT NULL CHECK (ready IN (0, 1))
                    );
                    CREATE TABLE IF NOT EXISTS recording_rows (
                        recording_id TEXT PRIMARY KEY,
                        received_at TEXT,
                        metadata_json TEXT NOT NULL,
                        counters_json TEXT NOT NULL
                    ) WITHOUT ROWID;
                    CREATE INDEX IF NOT EXISTS recording_page_order
                        ON recording_rows (received_at DESC, recording_id ASC);
                    CREATE TABLE IF NOT EXISTS source_receipts (
                        source_key TEXT PRIMARY KEY,
                        recording_id TEXT NOT NULL,
                        source_version INTEGER NOT NULL CHECK (source_version >= 1),
                        source_digest TEXT NOT NULL,
                        projection_json TEXT NOT NULL
                    ) WITHOUT ROWID;
                    """
                )
                connection.execute("BEGIN IMMEDIATE")
                state = connection.execute(
                    "SELECT schema_version, generation, ready "
                    "FROM catalog_state WHERE singleton = 1"
                ).fetchone()
                if state is None:
                    if existed and any(
                        connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                        for table in ("recording_rows", "source_receipts")
                    ):
                        raise RecordingCatalogError("catalog readiness authority is missing")
                    connection.execute("INSERT INTO catalog_state VALUES (1, ?, 1, 1)", (_SCHEMA,))
                elif state[0] != _SCHEMA or state[2] != 1:
                    raise RecordingCatalogError(
                        "catalog index is not ready or has an unknown schema"
                    )
                connection.commit()
            database_path.chmod(0o600)
            if not is_staged and not pointer_path.exists():
                atomic_replace_json(
                    pointer_path,
                    {
                        "schema_version": _ACTIVE_POINTER_SCHEMA,
                        "generation": 1,
                        "filename": database_path.name,
                    },
                )
        except RecordingCatalogError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError) as error:
            raise RecordingCatalogError("catalog index is missing or corrupt") from error

    def publish(
        self,
        *,
        source_key: str,
        source_version: int,
        recording_id: str,
        source_value: dict[str, Any],
        metadata_delta: dict[str, Any],
        counter_delta: dict[str, int],
    ) -> None:
        """Commit a source snapshot and its pending projection, then apply the projection."""
        with _process_lock(self.root / "publication.lock", self._thread_lock):
            self._publish_locked(
                source_key=source_key,
                source_version=source_version,
                recording_id=recording_id,
                source_value=source_value,
                metadata_delta=metadata_delta,
                counter_delta=counter_delta,
            )

    def publish_latest(
        self,
        *,
        source_key: str,
        recording_id: str,
        source_value: dict[str, Any],
        metadata_delta: dict[str, Any],
        counter_delta: dict[str, int],
    ) -> int:
        """Publish the next version of a source, treating an identical retry as a no-op."""
        with _process_lock(self.root / "publication.lock", self._thread_lock):
            old = self._read_optional(self._source_path(source_key))
            if old is not None and old.get("value") == source_value:
                return int(old["source_version"])
            version = 1 if old is None else int(old["source_version"]) + 1
            self._publish_locked(
                source_key=source_key,
                source_version=version,
                recording_id=recording_id,
                source_value=source_value,
                metadata_delta=metadata_delta,
                counter_delta=counter_delta,
            )
            return version

    def prepare_processor_run(
        self,
        *,
        run_id: str,
        recording_id: str,
        processor_type: str,
        status: str,
        old_state_digest: str | None,
        target_state_digest: str,
    ) -> None:
        """Record a compact run-state intent before its authoritative state commit."""
        source_key = f"processor-run:{run_id}"
        metadata_delta: dict[str, Any] = {}
        counter_delta = {f"processor_run:{processor_type}:{status}": 1}
        self._validate_publication(source_key, 1, recording_id, metadata_delta, counter_delta)
        if (
            not isinstance(run_id, str)
            or not run_id
            or not isinstance(processor_type, str)
            or not processor_type
            or not isinstance(status, str)
            or status not in {"queued", "running", "complete", "partial", "failed"}
            or not _is_digest(target_state_digest)
            or (old_state_digest is not None and not _is_digest(old_state_digest))
        ):
            raise RecordingCatalogError("processor-run publication intent is invalid")
        with _process_lock(self.root / "publication.lock", self._thread_lock):
            self.initialize()
            outbox_path = self._outbox_path(source_key)
            pending = self._read_optional(outbox_path)
            intent = {
                "schema_version": "recording-catalog-run-intent/v1",
                "source_key": source_key,
                "recording_id": recording_id,
                "run_id": run_id,
                "processor_type": processor_type,
                "status": status,
                "old_state_digest": old_state_digest,
                "target_state_digest": target_state_digest,
                "metadata": metadata_delta,
                "counters": counter_delta,
            }
            if pending is not None:
                if pending == intent:
                    return
                raise RecordingCatalogError("a source publication is already pending")
            atomic_replace_json(outbox_path, intent)

    def pending_processor_runs(self) -> tuple[dict[str, Any], ...]:
        """Return only explicit processor-run intents awaiting reconciliation."""
        with _process_lock(self.root / "publication.lock", self._thread_lock):
            if not self.outbox.exists():
                return ()
            records = []
            for path in sorted(self.outbox.glob("*.json")):
                record = self._read_required(path)
                if record.get("schema_version") == "recording-catalog-run-intent/v1":
                    self._validate_run_intent(record)
                    records.append(record)
            return tuple(records)

    def pending_processor_run(self, source_key: str) -> dict[str, Any] | None:
        """Read one exact processor-run intent without scanning the pending directory."""
        record = self.pending_processor_publication(source_key)
        if record is None or record.get("schema_version") != "recording-catalog-run-intent/v1":
            return None
        return record

    def pending_processor_publication(self, source_key: str) -> dict[str, Any] | None:
        """Read one exact run intent or publication record without scanning the outbox."""
        with _process_lock(self.root / "publication.lock", self._thread_lock):
            record = self._read_optional(self._outbox_path(source_key))
            if record is None:
                return None
            if record.get("schema_version") == "recording-catalog-run-intent/v1":
                self._validate_run_intent(record)
            elif record.get("schema_version") == "recording-catalog-outbox/v1":
                self._validate_outbox(record)
            else:
                raise RecordingCatalogError("pending processor-run publication is corrupt")
            if record.get("source_key") != source_key:
                raise RecordingCatalogError("pending processor-run source identity is corrupt")
            return record

    def finalize_processor_run(self, source_key: str, *, observed_state_digest: str) -> None:
        """Apply an intent after its exact authoritative run state has committed."""
        with _process_lock(self.root / "publication.lock", self._thread_lock):
            intent = self._read_required(self._outbox_path(source_key))
            self._validate_run_intent(intent)
            if intent["target_state_digest"] != observed_state_digest:
                raise RecordingCatalogError("processor-run target state digest does not match")
            source_value = {
                "run_id": intent["run_id"],
                "recording_id": intent["recording_id"],
                "processor_type": intent["processor_type"],
                "status": intent["status"],
            }
            source = {
                "schema_version": "recording-catalog-source/v1",
                "source_key": source_key,
                "source_version": self._next_source_version(source_key),
                "recording_id": intent["recording_id"],
                "value": source_value,
            }
            source_digest = _digest(source)
            publication = {
                "schema_version": "recording-catalog-outbox/v1",
                "source_key": source_key,
                "source_version": source["source_version"],
                "recording_id": intent["recording_id"],
                "source_digest": source_digest,
                "source": source,
                "projection": {
                    "metadata": intent["metadata"],
                    "counters": intent["counters"],
                },
            }
            atomic_replace_json(self._outbox_path(source_key), publication)
            self._apply(publication)

    def recover_processor_run_publication(
        self,
        source_key: str,
        *,
        source_value: dict[str, Any],
    ) -> bool:
        """Replay one ordinary run publication after confirming its exact source summary."""
        with _process_lock(self.root / "publication.lock", self._thread_lock):
            path = self._outbox_path(source_key)
            publication = self._read_optional(path)
            if publication is None or publication.get("schema_version") != (
                "recording-catalog-outbox/v1"
            ):
                return False
            self._validate_outbox(publication)
            if (
                publication["source_key"] != source_key
                or publication["source"]["value"] != source_value
            ):
                raise RecordingCatalogError(
                    "pending processor-run publication differs from its authoritative source"
                )
            self._apply(publication)
            return True

    def cancel_processor_run(self, source_key: str, *, observed_state_digest: str | None) -> None:
        """Remove an uncommitted intent after its exact prior state is confirmed."""
        with _process_lock(self.root / "publication.lock", self._thread_lock):
            path = self._outbox_path(source_key)
            intent = self._read_required(path)
            self._validate_run_intent(intent)
            if intent["old_state_digest"] != observed_state_digest:
                raise RecordingCatalogError("processor-run prior state digest does not match")
            path.unlink()

    def _next_source_version(self, source_key: str) -> int:
        old = self._read_optional(self._source_path(source_key))
        if old is None:
            return 1
        return int(old["source_version"]) + 1

    @staticmethod
    def _validate_run_intent(record: dict[str, Any]) -> None:
        expected = {
            "schema_version",
            "source_key",
            "recording_id",
            "run_id",
            "processor_type",
            "status",
            "old_state_digest",
            "target_state_digest",
            "metadata",
            "counters",
        }
        if (
            set(record) != expected
            or record.get("schema_version") != "recording-catalog-run-intent/v1"
            or record.get("source_key") != f"processor-run:{record.get('run_id')}"
            or not isinstance(record.get("run_id"), str)
            or not isinstance(record.get("recording_id"), str)
            or not isinstance(record.get("processor_type"), str)
            or not isinstance(record.get("status"), str)
            or record.get("status") not in {"queued", "running", "complete", "partial", "failed"}
            or not _is_digest(record.get("target_state_digest"))
            or (
                record.get("old_state_digest") is not None
                and not _is_digest(record["old_state_digest"])
            )
            or not isinstance(record.get("metadata"), dict)
            or not isinstance(record.get("counters"), dict)
        ):
            raise RecordingCatalogError("processor-run publication intent is corrupt")
        RecordingCatalogIndex._validate_publication(
            record["source_key"],
            1,
            record["recording_id"],
            record["metadata"],
            record["counters"],
        )
        if record["metadata"] != {} or record["counters"] != {
            f"processor_run:{record['processor_type']}:{record['status']}": 1
        }:
            raise RecordingCatalogError("processor-run projection is not compact")

    def _publish_locked(
        self,
        *,
        source_key: str,
        source_version: int,
        recording_id: str,
        source_value: dict[str, Any],
        metadata_delta: dict[str, Any],
        counter_delta: dict[str, int],
    ) -> None:
        self._validate_publication(
            source_key, source_version, recording_id, metadata_delta, counter_delta
        )
        self.initialize()
        self._recover_pending_locked()
        source_path = self._source_path(source_key)
        outbox_path = self._outbox_path(source_key)
        source_record = {
            "schema_version": "recording-catalog-source/v1",
            "source_key": source_key,
            "source_version": source_version,
            "recording_id": recording_id,
            "value": source_value,
        }
        source_digest = _digest(source_record)
        projection = {"metadata": metadata_delta, "counters": counter_delta}
        pending_record = {
            "schema_version": "recording-catalog-outbox/v1",
            "source_key": source_key,
            "source_version": source_version,
            "recording_id": recording_id,
            "source_digest": source_digest,
            "source": source_record,
            "projection": projection,
        }
        old_pending = self._read_optional(outbox_path)
        if old_pending is not None:
            raise RecordingCatalogError("a source publication is already pending")
        old_source = self._read_optional(source_path)
        if old_source is not None:
            old_version = old_source.get("source_version")
            if old_version == source_version and _digest(old_source) == source_digest:
                self._apply(pending_record)
                return
            elif old_version != source_version - 1:
                raise RecordingCatalogError("source version conflicts with its durable receipt")
        elif source_version != 1:
            raise RecordingCatalogError("first source version must be one")

        # The pending record is also the source authority until the index commit completes.
        # One atomic write therefore commits the source and its outbox entry together.
        # Recovery enumerates only this explicit pending directory.
        self.sources.mkdir(parents=True, exist_ok=True)
        self.outbox.mkdir(parents=True, exist_ok=True)
        atomic_replace_json(outbox_path, pending_record)
        self._apply(pending_record)

    def recover_pending(self) -> int:
        """Replay only explicitly pending source publications."""
        with _process_lock(self.root / "publication.lock", self._thread_lock):
            return self._recover_pending_locked()

    def _recover_pending_locked(self) -> int:
        self.initialize()
        if not self.outbox.exists():
            return 0
        pending = sorted(self.outbox.glob("*.json"))
        recovered = 0
        for path in pending:
            record = self._read_required(path)
            if record.get("schema_version") == "recording-catalog-run-intent/v1":
                self._validate_run_intent(record)
                continue
            source = record.get("source")
            if (
                not isinstance(source, dict)
                or source.get("source_version") != record.get("source_version")
                or source.get("recording_id") != record.get("recording_id")
                or source.get("schema_version") != "recording-catalog-source/v1"
                or source.get("source_key") != record.get("source_key")
                or _digest(source) != record.get("source_digest")
            ):
                raise RecordingCatalogError("pending publication source is absent or corrupt")
            self._apply(record)
            recovered += 1
        return recovered

    def read(self, recording_id: str) -> dict[str, Any] | None:
        """Read one compact recording row without source access or reconstruction."""
        try:
            with closing(self._connect()) as connection:
                state = connection.execute(
                    "SELECT schema_version, ready FROM catalog_state WHERE singleton = 1"
                ).fetchone()
                if state != (_SCHEMA, 1):
                    raise RecordingCatalogError("catalog index is not ready")
                row = connection.execute(
                    "SELECT recording_id, received_at, metadata_json, counters_json "
                    "FROM recording_rows WHERE recording_id = ?",
                    (recording_id,),
                ).fetchone()
                if row is None:
                    return None
                return {
                    "recording_id": row[0],
                    "received_at": row[1],
                    "metadata": json.loads(row[2]),
                    "counters": json.loads(row[3]),
                }
        except RecordingCatalogError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError, TypeError) as error:
            raise RecordingCatalogError("catalog read failed") from error

    def page(
        self,
        *,
        limit: int,
        after: tuple[str | None, str] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Read a bounded page in stable order."""
        if not 1 <= limit <= 100 or (
            after is not None
            and (
                len(after) != 2
                or (after[0] is not None and not isinstance(after[0], str))
                or not isinstance(after[1], str)
            )
        ):
            raise RecordingCatalogError("catalog page bounds are invalid")
        try:
            with closing(self._connect()) as connection:
                state = connection.execute(
                    "SELECT schema_version, ready FROM catalog_state WHERE singleton = 1"
                ).fetchone()
                if state != (_SCHEMA, 1):
                    raise RecordingCatalogError("catalog index is not ready")
                if after is None:
                    rows = connection.execute(
                        "SELECT recording_id, received_at, metadata_json, counters_json "
                        "FROM recording_rows ORDER BY received_at DESC, recording_id ASC "
                        "LIMIT ?",
                        (limit,),
                    ).fetchall()
                else:
                    if after[0] is None:
                        rows = connection.execute(
                            "SELECT recording_id, received_at, metadata_json, counters_json "
                            "FROM recording_rows WHERE received_at IS NULL AND recording_id > ? "
                            "ORDER BY received_at DESC, recording_id ASC LIMIT ?",
                            (after[1], limit),
                        ).fetchall()
                    else:
                        rows = connection.execute(
                            "SELECT recording_id, received_at, metadata_json, counters_json "
                            "FROM recording_rows WHERE received_at < ? "
                            "OR (received_at = ? AND recording_id > ?) "
                            "OR received_at IS NULL "
                            "ORDER BY received_at DESC, recording_id ASC LIMIT ?",
                            (after[0], after[0], after[1], limit),
                        ).fetchall()
            return tuple(
                {
                    "recording_id": row[0],
                    "received_at": row[1],
                    "metadata": json.loads(row[2]),
                    "counters": json.loads(row[3]),
                }
                for row in rows
            )
        except RecordingCatalogError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError, TypeError) as error:
            raise RecordingCatalogError("catalog page read failed") from error

    def rebuild(self, source_records: list[dict[str, Any]]) -> None:
        """Build and validate a staged generation from an explicit offline source snapshot."""
        with _process_lock(self.root / "publication.lock", self._thread_lock):
            self._rebuild_locked(source_records)

    def _rebuild_locked(self, source_records: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        generations = self.root / "generations"
        generations.mkdir(parents=True, exist_ok=True)
        staged = generations / "catalog.staged.sqlite3"
        staged.unlink(missing_ok=True)
        Path(f"{staged}-wal").unlink(missing_ok=True)
        Path(f"{staged}-shm").unlink(missing_ok=True)
        rebuilt = RecordingCatalogIndex(
            self.root.parent,
            _database_override=staged,
        )
        rebuilt.initialize()
        current_generation = 0
        try:
            self._database_path()
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT schema_version, generation FROM catalog_state WHERE singleton = 1"
                ).fetchone()
                if row is not None and row[0] == _SCHEMA:
                    current_generation = row[1]
        except (OSError, sqlite3.DatabaseError, RecordingCatalogError):
            current_generation = 0
        existing_generations = [
            int(path.stem.removeprefix("catalog-generation-"))
            for path in generations.glob("catalog-generation-*.sqlite3")
            if path.stem.removeprefix("catalog-generation-").isdigit()
        ]
        next_generation = max([current_generation, *existing_generations], default=0) + 1
        with closing(rebuilt._connect()) as connection:
            connection.execute(
                "UPDATE catalog_state SET generation = ? WHERE singleton = 1",
                (next_generation,),
            )
        for source in source_records:
            source_value = {
                "schema_version": "recording-catalog-source/v1",
                "source_key": source["source_key"],
                "source_version": source["source_version"],
                "recording_id": source["recording_id"],
                "value": source["source_value"],
            }
            rebuilt._apply(
                {
                    "schema_version": "recording-catalog-outbox/v1",
                    "source_key": source["source_key"],
                    "source_version": source["source_version"],
                    "recording_id": source["recording_id"],
                    "source_digest": _digest(source_value),
                    "source": source_value,
                    "projection": {"metadata": source["metadata"], "counters": source["counters"]},
                },
                remove_pending=False,
                allow_initial_source_version=True,
            )
        with closing(rebuilt._connect()) as connection:
            rebuilt._check_integrity(connection)
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode = DELETE")
        final_path = generations / f"catalog-generation-{next_generation:08d}.sqlite3"
        staged.replace(final_path)
        atomic_replace_json(
            self.root / "active-catalog.json",
            {
                "schema_version": _ACTIVE_POINTER_SCHEMA,
                "generation": next_generation,
                "filename": final_path.name,
            },
        )

    def _apply(
        self,
        record: dict[str, Any],
        *,
        remove_pending: bool = True,
        allow_initial_source_version: bool = False,
    ) -> None:
        self._validate_outbox(record)
        source_key = record["source_key"]
        recording_id = record["recording_id"]
        version = record["source_version"]
        digest = record["source_digest"]
        projection = record["projection"]
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT recording_id, source_version, source_digest, projection_json "
                    "FROM source_receipts WHERE source_key = ?",
                    (source_key,),
                ).fetchone()
                if current is not None and current[1] == version:
                    if (
                        current[:3] != (recording_id, version, digest)
                        or current[3] != _canonical(projection).decode()
                    ):
                        raise RecordingCatalogError(
                            "source version was replayed with different content"
                        )
                    connection.commit()
                else:
                    if current is not None and current[0] != recording_id:
                        raise RecordingCatalogError("source recording identity cannot change")
                    expected = (
                        (version if allow_initial_source_version else 1)
                        if current is None
                        else current[1] + 1
                    )
                    if version != expected:
                        raise RecordingCatalogError("source version conflicts with catalog receipt")
                    old_projection = {} if current is None else json.loads(current[3])
                    row = connection.execute(
                        "SELECT metadata_json, counters_json FROM recording_rows "
                        "WHERE recording_id = ?",
                        (recording_id,),
                    ).fetchone()
                    metadata = {} if row is None else json.loads(row[0])
                    counters = {} if row is None else json.loads(row[1])
                    old_counters = old_projection.get("counters", {})
                    new_counters = projection["counters"]
                    for key in set(old_counters) | set(new_counters):
                        value = (
                            counters.get(key, 0)
                            - old_counters.get(key, 0)
                            + new_counters.get(key, 0)
                        )
                        if value < 0:
                            raise RecordingCatalogError(
                                "catalog counter delta would become negative"
                            )
                        if value:
                            counters[key] = value
                        else:
                            counters.pop(key, None)
                    metadata.update(projection["metadata"])
                    received_at = metadata.get("received_at")
                    connection.execute(
                        "INSERT INTO recording_rows VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(recording_id) DO UPDATE SET received_at=excluded.received_at, "
                        "metadata_json=excluded.metadata_json, "
                        "counters_json=excluded.counters_json",
                        (
                            recording_id,
                            received_at,
                            _canonical(metadata).decode(),
                            _canonical(counters).decode(),
                        ),
                    )
                    connection.execute(
                        "INSERT INTO source_receipts VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT(source_key) DO UPDATE SET recording_id=excluded.recording_id, "
                        "source_version=excluded.source_version, "
                        "source_digest=excluded.source_digest, "
                        "projection_json=excluded.projection_json",
                        (
                            source_key,
                            recording_id,
                            version,
                            digest,
                            _canonical(projection).decode(),
                        ),
                    )
                    connection.commit()
            pending_path = self._outbox_path(source_key)
            if remove_pending and pending_path.exists():
                self._source_path(source_key).parent.mkdir(parents=True, exist_ok=True)
                atomic_replace_json(self._source_path(source_key), record["source"])
                pending_path.unlink()
        except RecordingCatalogError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise RecordingCatalogError("catalog publication failed") from error

    def _connect(self, *, create: bool = False) -> sqlite3.Connection:
        database_path = self._database_path(allow_initial=create)
        if create:
            database_path.parent.mkdir(parents=True, exist_ok=True)
        if not create and not database_path.is_file():
            raise RecordingCatalogError("catalog index is absent")
        connection = sqlite3.connect(database_path, timeout=10, isolation_level=None)
        connection.row_factory = None
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @staticmethod
    def _check_integrity(connection: sqlite3.Connection) -> None:
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RecordingCatalogError("catalog index integrity check failed")

    @staticmethod
    def _validate_publication(
        source_key: str,
        source_version: int,
        recording_id: str,
        metadata: dict[str, Any],
        counters: dict[str, int],
    ) -> None:
        if not source_key or "/" in source_key or "\\" in source_key or source_version < 1:
            raise RecordingCatalogError("source identity or version is invalid")
        if not recording_id or any(not key for key in metadata):
            raise RecordingCatalogError("recording projection identity is invalid")
        if any(
            not key or not isinstance(value, int) or isinstance(value, bool)
            for key, value in counters.items()
        ):
            raise RecordingCatalogError("catalog counters must be integer deltas")

    @staticmethod
    def _validate_outbox(record: dict[str, Any]) -> None:
        if (
            set(record)
            != {
                "schema_version",
                "source_key",
                "source_version",
                "recording_id",
                "source_digest",
                "source",
                "projection",
            }
            or record["schema_version"] != "recording-catalog-outbox/v1"
            or not isinstance(record["source_version"], int)
            or not isinstance(record["projection"], dict)
            or set(record["projection"]) != {"metadata", "counters"}
            or not isinstance(record["projection"]["metadata"], dict)
            or not isinstance(record["projection"]["counters"], dict)
        ):
            raise RecordingCatalogError("pending catalog publication is corrupt")
        RecordingCatalogIndex._validate_publication(
            record["source_key"],
            record["source_version"],
            record["recording_id"],
            record["projection"]["metadata"],
            record["projection"]["counters"],
        )
        source = record["source"]
        if (
            not isinstance(source, dict)
            or source.get("schema_version") != "recording-catalog-source/v1"
            or source.get("source_key") != record["source_key"]
            or source.get("source_version") != record["source_version"]
            or source.get("recording_id") != record["recording_id"]
            or _digest(source) != record["source_digest"]
        ):
            raise RecordingCatalogError("pending publication source is absent or corrupt")

    def _source_path(self, source_key: str) -> Path:
        if not source_key or "/" in source_key or "\\" in source_key:
            raise RecordingCatalogError("source identity is invalid")
        return self.sources / f"{source_key}.json"

    def _outbox_path(self, source_key: str) -> Path:
        if not source_key or "/" in source_key or "\\" in source_key:
            raise RecordingCatalogError("source identity is invalid")
        return self.outbox / f"{source_key}.json"

    @staticmethod
    def _read_required(path: Path) -> dict[str, Any]:
        value = RecordingCatalogIndex._read_optional(path)
        if value is None:
            raise RecordingCatalogError("pending publication source is absent")
        return value

    @staticmethod
    def _read_optional(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_bytes())
            if not isinstance(value, dict) or _canonical(value) != path.read_bytes():
                raise ValueError("non-canonical source record")
            return value
        except FileNotFoundError:
            return None
        except (OSError, TypeError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise RecordingCatalogError("catalog source record is corrupt") from error
