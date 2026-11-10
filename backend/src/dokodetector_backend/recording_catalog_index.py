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


class RecordingCatalogError(RuntimeError):
    """The recording catalog is not ready or its publication contract is invalid."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class RecordingCatalogIndex:
    """Apply source-owned deltas to one versioned SQLite metadata index."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root) / "recording-catalog"
        self.path = self.root / "catalog.sqlite3"
        self.sources = self.root / "sources"
        self.outbox = self.root / "outbox"
        self._thread_lock = RLock()

    def initialize(self) -> None:
        if not self.path.exists() and (self.sources.exists() or self.outbox.exists()):
            raise RecordingCatalogError("catalog index is absent while source publications exist")
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
            self.path.chmod(0o600)
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
        for path in pending:
            record = self._read_required(path)
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
        return len(pending)

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
        after: tuple[str, str] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Read a bounded page in stable order."""
        if not 1 <= limit <= 100 or (
            after is not None
            and (len(after) != 2 or not all(isinstance(value, str) for value in after))
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
                    rows = connection.execute(
                        "SELECT recording_id, received_at, metadata_json, counters_json "
                        "FROM recording_rows WHERE received_at < ? "
                        "OR (received_at = ? AND recording_id > ?) "
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
        staged = self.root / "catalog.staged.sqlite3"
        staged.unlink(missing_ok=True)
        Path(f"{staged}-wal").unlink(missing_ok=True)
        Path(f"{staged}-shm").unlink(missing_ok=True)
        rebuilt = RecordingCatalogIndex.__new__(RecordingCatalogIndex)
        rebuilt.root = self.root
        rebuilt.path = staged
        rebuilt.sources = self.root / "catalog-rebuild-sources"
        rebuilt.outbox = self.root / "catalog-rebuild-outbox"
        rebuilt.initialize()
        current_generation = 0
        if self.path.exists():
            try:
                with closing(self._connect()) as connection:
                    row = connection.execute(
                        "SELECT schema_version, generation FROM catalog_state WHERE singleton = 1"
                    ).fetchone()
                    if row is not None and row[0] == _SCHEMA:
                        current_generation = row[1]
            except (OSError, sqlite3.DatabaseError, RecordingCatalogError):
                current_generation = 0
        with closing(rebuilt._connect()) as connection:
            connection.execute(
                "UPDATE catalog_state SET generation = ? WHERE singleton = 1",
                (current_generation + 1,),
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
            )
        with closing(rebuilt._connect()) as connection:
            rebuilt._check_integrity(connection)
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode = DELETE")
        Path(f"{self.path}-wal").unlink(missing_ok=True)
        Path(f"{self.path}-shm").unlink(missing_ok=True)
        staged.replace(self.path)

    def _apply(self, record: dict[str, Any], *, remove_pending: bool = True) -> None:
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
                    expected = 1 if current is None else current[1] + 1
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
        if not create and not self.path.is_file():
            raise RecordingCatalogError("catalog index is absent")
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
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
