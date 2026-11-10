from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Event

import pytest

import dokodetector_backend.recording_catalog_index as catalog_module
from dokodetector_backend.recording_catalog_index import (
    RecordingCatalogError,
    RecordingCatalogIndex,
)


def _publish(
    index: RecordingCatalogIndex,
    *,
    source_key: str = "fixture-source",
    version: int = 1,
    recording_id: str = "recording-1",
    value: str = "source-value",
    received_at: str | None = "2026-11-10T10:00:00Z",
    counter_delta: dict[str, int] | None = None,
) -> None:
    index.publish(
        source_key=source_key,
        source_version=version,
        recording_id=recording_id,
        source_value={"value": value},
        metadata_delta={"received_at": received_at, "fixture_label": value},
        counter_delta=counter_delta or {"source_items": 1},
    )


def test_source_write_projects_metadata_and_survives_restart(tmp_path: Path) -> None:
    first = RecordingCatalogIndex(tmp_path)
    _publish(first)

    assert first.read("recording-1") == {
        "recording_id": "recording-1",
        "received_at": "2026-11-10T10:00:00Z",
        "metadata": {"fixture_label": "source-value", "received_at": "2026-11-10T10:00:00Z"},
        "counters": {"source_items": 1},
    }
    assert (tmp_path / "recording-catalog/sources/fixture-source.json").is_file()
    assert not (tmp_path / "recording-catalog/outbox/fixture-source.json").exists()

    restarted = RecordingCatalogIndex(tmp_path)
    assert restarted.read("recording-1") == first.read("recording-1")


def test_replay_is_idempotent_and_conflicts_are_rejected(tmp_path: Path) -> None:
    index = RecordingCatalogIndex(tmp_path)
    _publish(index)
    _publish(index)
    assert index.read("recording-1")["counters"] == {"source_items": 1}

    with pytest.raises(RecordingCatalogError, match="version conflicts"):
        _publish(index, value="different")
    with pytest.raises(RecordingCatalogError, match="version conflicts"):
        _publish(index, version=3, value="gap")


def test_new_source_version_replaces_its_counter_contribution(tmp_path: Path) -> None:
    index = RecordingCatalogIndex(tmp_path)
    _publish(index, counter_delta={"source_items": 1})
    _publish(index, version=2, value="updated", counter_delta={"source_items": 3})
    assert index.read("recording-1")["counters"] == {"source_items": 3}
    assert index.read("recording-1")["metadata"]["fixture_label"] == "updated"


def test_rebuild_accepts_current_source_versions_above_one(tmp_path: Path) -> None:
    index = RecordingCatalogIndex(tmp_path)
    _publish(index)
    _publish(index, version=2, value="current", counter_delta={"source_items": 4})
    index.rebuild(
        [
            {
                "source_key": "fixture-source",
                "source_version": 2,
                "recording_id": "recording-1",
                "source_value": {"value": "current"},
                "metadata": {
                    "received_at": "2026-11-10T10:00:00Z",
                    "fixture_label": "current",
                },
                "counters": {"source_items": 4},
            }
        ]
    )
    assert index.read("recording-1")["counters"] == {"source_items": 4}
    with sqlite3.connect(index.path) as connection:
        assert connection.execute(
            "SELECT source_version FROM source_receipts WHERE source_key = 'fixture-source'"
        ).fetchone() == (2,)


def test_recovery_replays_pending_delta_after_index_commit_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = RecordingCatalogIndex(tmp_path)
    original_unlink = Path.unlink

    def crash_before_outbox_removal(path: Path, *args, **kwargs):
        if path.name == "fixture-source.json" and path.parent.name == "outbox":
            raise OSError("simulated crash after index commit")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", crash_before_outbox_removal)
    with pytest.raises(RecordingCatalogError, match="publication failed"):
        _publish(index)
    monkeypatch.setattr(Path, "unlink", original_unlink)

    restarted = RecordingCatalogIndex(tmp_path)
    assert restarted.recover_pending() == 1
    assert restarted.read("recording-1")["counters"] == {"source_items": 1}
    assert restarted.recover_pending() == 0


def test_restart_applies_durable_outbox_after_source_commit(tmp_path: Path) -> None:
    index = RecordingCatalogIndex(tmp_path)
    original_apply = index._apply
    index._apply = lambda _record: (_ for _ in ()).throw(RuntimeError("crash before index commit"))
    with pytest.raises(RuntimeError, match="before index"):
        _publish(index)
    index._apply = original_apply

    restarted = RecordingCatalogIndex(tmp_path)
    assert restarted.read("recording-1") is None
    assert restarted.recover_pending() == 1
    assert restarted.read("recording-1")["counters"] == {"source_items": 1}


def test_recovery_requires_the_exact_valid_source_record(tmp_path: Path) -> None:
    index = RecordingCatalogIndex(tmp_path)
    _publish(index)
    original_apply = index._apply
    index._apply = lambda _record: (_ for _ in ()).throw(RuntimeError("crash before index"))
    with pytest.raises(RuntimeError, match="crash before index"):
        _publish(index, source_key="broken-source", recording_id="recording-broken")
    index._apply = original_apply

    outbox_path = tmp_path / "recording-catalog/outbox/broken-source.json"
    outbox = json.loads(outbox_path.read_bytes())
    del outbox["source"]
    outbox_path.write_text(
        json.dumps(outbox, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    with pytest.raises(RecordingCatalogError, match="absent"):
        index.recover_pending()
    assert index.read("recording-1")["counters"] == {"source_items": 1}


def test_concurrent_publications_keep_counters_and_reads_consistent(tmp_path: Path) -> None:
    index = RecordingCatalogIndex(tmp_path)
    index.initialize()

    def write(number: int) -> None:
        _publish(
            index,
            source_key=f"source-{number}",
            recording_id="recording-shared",
            value=f"value-{number}",
            counter_delta={"source_items": 1},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(20)))
        reads = list(pool.map(lambda _: index.read("recording-shared"), range(20)))
    assert all(row is not None for row in reads)
    assert index.read("recording-shared")["counters"] == {"source_items": 20}


def test_page_query_is_bounded_under_tenfold_source_growth(tmp_path: Path) -> None:
    index = RecordingCatalogIndex(tmp_path)
    for number in range(10):
        _publish(
            index,
            source_key=f"source-{number}",
            recording_id=f"recording-{number:02d}",
            value=f"value-{number}",
            received_at=f"2026-11-{number + 1:02d}T10:00:00Z",
        )

    page = index.page(limit=3)
    assert len(page) == 3
    assert [row["recording_id"] for row in page] == [
        "recording-09",
        "recording-08",
        "recording-07",
    ]
    cursor = (page[-1]["received_at"], page[-1]["recording_id"])
    next_page = index.page(limit=3, after=cursor)
    assert len(next_page) == 3
    assert next_page[0]["recording_id"] == "recording-06"


def test_keyset_pages_include_null_received_at_rows(tmp_path: Path) -> None:
    index = RecordingCatalogIndex(tmp_path)
    _publish(index, source_key="new", recording_id="new", received_at="2026-11-10T10:00:00Z")
    _publish(index, source_key="old", recording_id="old", received_at="2026-11-09T10:00:00Z")
    _publish(index, source_key="null-b", recording_id="null-b", received_at=None)
    _publish(index, source_key="null-a", recording_id="null-a", received_at=None)

    first = index.page(limit=2)
    second = index.page(limit=2, after=(first[-1]["received_at"], first[-1]["recording_id"]))
    assert [row["recording_id"] for row in first] == ["new", "old"]
    assert [row["recording_id"] for row in second] == ["null-a", "null-b"]
    assert index.page(limit=2, after=(second[-1]["received_at"], second[-1]["recording_id"])) == ()


def test_rebuild_uses_explicit_source_snapshot_and_switches_index(tmp_path: Path) -> None:
    index = RecordingCatalogIndex(tmp_path)
    _publish(index)
    source_snapshot = [
        {
            "source_key": "fixture-source",
            "source_version": 1,
            "recording_id": "recording-rebuilt",
            "source_value": {"value": "rebuild"},
            "metadata": {"received_at": "2026-11-10T12:00:00Z", "fixture_label": "rebuild"},
            "counters": {"source_items": 2},
        }
    ]
    index.rebuild(source_snapshot)
    assert index.read("recording-1") is None
    assert index.read("recording-rebuilt")["counters"] == {"source_items": 2}
    with index._connect() as connection:
        assert connection.execute(
            "SELECT generation FROM catalog_state WHERE singleton = 1"
        ).fetchone() == (2,)
    assert (
        json.loads((tmp_path / "recording-catalog/sources/fixture-source.json").read_bytes())[
            "recording_id"
        ]
        == "recording-1"
    )


def test_generation_switch_keeps_an_open_reader_on_its_snapshot(tmp_path: Path) -> None:
    index = RecordingCatalogIndex(tmp_path)
    _publish(index, value="before")
    reader_open = Event()
    continue_read = Event()

    def read_old_generation() -> str:
        with closing(sqlite3.connect(index.path, isolation_level=None)) as reader:
            reader.execute("BEGIN")
            before = reader.execute(
                "SELECT metadata_json FROM recording_rows WHERE recording_id = 'recording-1'"
            ).fetchone()[0]
            reader_open.set()
            assert continue_read.wait(5)
            after = reader.execute(
                "SELECT metadata_json FROM recording_rows WHERE recording_id = 'recording-1'"
            ).fetchone()[0]
            assert "before" in before
            return after

    with ThreadPoolExecutor(max_workers=1) as pool:
        reader_task = pool.submit(read_old_generation)
        assert reader_open.wait(5)
        index.rebuild(
            [
                {
                    "source_key": "fixture-source",
                    "source_version": 2,
                    "recording_id": "recording-1",
                    "source_value": {"value": "after"},
                    "metadata": {
                        "received_at": "2026-11-10T10:00:00Z",
                        "fixture_label": "after",
                    },
                    "counters": {"source_items": 1},
                }
            ]
        )
        continue_read.set()
        assert "before" in reader_task.result(timeout=5)
    assert index.read("recording-1")["metadata"]["fixture_label"] == "after"


def test_interrupted_generation_switch_preserves_committed_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = RecordingCatalogIndex(tmp_path)
    _publish(index, value="committed")
    original_atomic_replace = catalog_module.atomic_replace_json

    def fail_pointer_write(path: Path, value):
        if path.name == "active-catalog.json":
            raise OSError("simulated interruption before pointer switch")
        return original_atomic_replace(path, value)

    monkeypatch.setattr(catalog_module, "atomic_replace_json", fail_pointer_write)
    with pytest.raises(OSError, match="pointer switch"):
        index.rebuild(
            [
                {
                    "source_key": "fixture-source",
                    "source_version": 2,
                    "recording_id": "recording-1",
                    "source_value": {"value": "uncommitted"},
                    "metadata": {
                        "received_at": "2026-11-10T10:00:00Z",
                        "fixture_label": "uncommitted",
                    },
                    "counters": {"source_items": 5},
                }
            ]
        )
    monkeypatch.setattr(catalog_module, "atomic_replace_json", original_atomic_replace)
    assert index.read("recording-1")["metadata"]["fixture_label"] == "committed"
    assert index.read("recording-1")["counters"] == {"source_items": 1}
    index.rebuild(
        [
            {
                "source_key": "fixture-source",
                "source_version": 2,
                "recording_id": "recording-1",
                "source_value": {"value": "retry"},
                "metadata": {
                    "received_at": "2026-11-10T10:00:00Z",
                    "fixture_label": "retry",
                },
                "counters": {"source_items": 2},
            }
        ]
    )
    pointer = json.loads((index.root / "active-catalog.json").read_bytes())
    with sqlite3.connect(index.path) as connection:
        assert connection.execute(
            "SELECT generation FROM catalog_state WHERE singleton = 1"
        ).fetchone() == (pointer["generation"],)
    assert index.read("recording-1")["metadata"]["fixture_label"] == "retry"


def test_missing_catalog_with_source_state_is_visible(tmp_path: Path) -> None:
    source = tmp_path / "recording-catalog/sources/source.json"
    source.parent.mkdir(parents=True)
    source.write_text("{}", encoding="utf-8")
    index = RecordingCatalogIndex(tmp_path)
    with pytest.raises(RecordingCatalogError, match="index is absent"):
        index.initialize()
    index.rebuild(
        [
            {
                "source_key": "source",
                "source_version": 1,
                "recording_id": "recording-rebuilt",
                "source_value": {"value": "offline"},
                "metadata": {"received_at": "2026-11-10T12:00:00Z"},
                "counters": {"source_items": 1},
            }
        ]
    )
    assert index.read("recording-rebuilt")["counters"] == {"source_items": 1}


def test_corrupt_index_is_visible_without_source_reconstruction(tmp_path: Path) -> None:
    index = RecordingCatalogIndex(tmp_path)
    _publish(index)
    index.path.write_bytes(b"not a sqlite database")
    with pytest.raises(RecordingCatalogError, match="read failed"):
        index.read("recording-1")
    index.rebuild(
        [
            {
                "source_key": "fixture-source",
                "source_version": 1,
                "recording_id": "recording-1",
                "source_value": {"value": "source-value"},
                "metadata": {
                    "received_at": "2026-11-10T10:00:00Z",
                    "fixture_label": "source-value",
                },
                "counters": {"source_items": 1},
            }
        ]
    )
    assert index.read("recording-1")["counters"] == {"source_items": 1}


def test_missing_active_generation_is_visible(tmp_path: Path) -> None:
    index = RecordingCatalogIndex(tmp_path)
    _publish(index)
    index.path.unlink()
    with pytest.raises(RecordingCatalogError, match="generation is absent"):
        index.initialize()
