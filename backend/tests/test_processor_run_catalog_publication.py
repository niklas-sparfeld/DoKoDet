from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from doko_operations.pipeline_data import (
    ProcessorRunRequest,
    RunFailure,
    RunProgress,
    canonical_processor_run_state_bytes,
)
from test_pipeline_store import request
from test_round_analysis_api import RECORDING_ID, _backend

from dokodetector_backend import processor_run_store as run_store_module
from dokodetector_backend import recording_catalog_index as catalog_module
from dokodetector_backend.pipeline_storage import PipelineRuntimeStorage, PipelineStoreError
from dokodetector_backend.processor_run_store import ProcessorRunStore
from dokodetector_backend.recording_catalog_index import (
    RecordingCatalogError,
    RecordingCatalogIndex,
)


def _stores(root: Path) -> tuple[ProcessorRunStore, RecordingCatalogIndex]:
    catalog = RecordingCatalogIndex(root)
    catalog.initialize()
    store = ProcessorRunStore(PipelineRuntimeStorage(root / "runtime", root), catalog_index=catalog)
    return store, catalog


def _request(run_id: str = "catalog-run"):
    value = request(run_id).to_mapping()
    value["input_revision_ids"] = []
    return ProcessorRunRequest.from_mapping(value)


def test_processor_run_status_transitions_replay_and_progress_counts(tmp_path: Path) -> None:
    store, catalog = _stores(tmp_path)
    store._validate_output_revisions = lambda *_args, **_kwargs: None
    created, is_new = store.create(_request(), created_at="2026-09-05T10:00:00Z")
    assert is_new is True
    assert created.state.status == "queued"
    assert catalog.read("recording-01")["counters"] == {"processor_run:event-detection:queued": 1}

    assert store.create(_request(), created_at="2026-09-05T10:00:00Z")[1] is False
    store.start("catalog-run", started_at="2026-09-05T10:01:00Z")
    for completed in range(1, 11):
        store.update_progress(
            "catalog-run",
            progress=RunProgress(completed=completed, total=10),
            updated_at=f"2026-09-05T10:01:{completed:02d}Z",
        )
    assert catalog.read("recording-01")["counters"] == {"processor_run:event-detection:running": 1}

    store.partial(
        "catalog-run",
        progress=RunProgress(completed=1, total=2),
        items=(),
        completed_at="2026-09-05T10:02:00Z",
    )
    assert catalog.read("recording-01")["counters"] == {"processor_run:event-detection:partial": 1}
    store.retry("catalog-run", started_at="2026-09-05T10:03:00Z")
    store.fail(
        "catalog-run",
        RunFailure(code="processor_failed", message="processor failed"),
        completed_at="2026-09-05T10:04:00Z",
    )
    store.retry("catalog-run", started_at="2026-09-05T10:05:00Z")
    store.complete(
        "catalog-run",
        ("output-r1",),
        completed_at="2026-09-05T10:06:00Z",
    )
    assert catalog.read("recording-01")["counters"] == {"processor_run:event-detection:complete": 1}

    restarted, restarted_catalog = _stores(tmp_path)
    assert restarted.recover_catalog_publications() == 0
    assert restarted_catalog.read("recording-01")["counters"] == {
        "processor_run:event-detection:complete": 1
    }


def test_pending_run_intent_cancels_when_source_state_did_not_commit(tmp_path: Path) -> None:
    store, catalog = _stores(tmp_path)
    run, _ = store.create(_request())
    old_bytes = store.state_path(run.run_id).read_bytes()
    target = replace(run.state, status="running", started_at="2026-09-05T10:01:00Z")
    target_bytes = canonical_processor_run_state_bytes(target)
    store._prepare_run_catalog_intent(
        run.request,
        target,
        old_state_digest=hashlib.sha256(old_bytes).hexdigest(),
        target_state_bytes=target_bytes,
    )

    restarted, restarted_catalog = _stores(tmp_path)
    assert restarted.recover_catalog_publications() == 1
    assert restarted.require(run.run_id).state.status == "queued"
    assert restarted_catalog.read("recording-01")["counters"] == {
        "processor_run:event-detection:queued": 1
    }
    assert restarted_catalog.pending_processor_runs() == ()


def test_create_intent_cancels_when_staged_run_never_commits(tmp_path: Path, monkeypatch) -> None:
    store, catalog = _stores(tmp_path)

    def stop_before_directory_commit(*_args, **_kwargs):
        raise OSError("simulated stop before run directory commit")

    monkeypatch.setattr(run_store_module, "commit_staged_directory", stop_before_directory_commit)
    with pytest.raises(PipelineStoreError, match="could not be created"):
        store.create(_request())
    monkeypatch.undo()

    assert not store.run_path("catalog-run").exists()
    assert len(catalog.pending_processor_runs()) == 1
    restarted, restarted_catalog = _stores(tmp_path)
    assert restarted.recover_catalog_publications() == 1
    assert restarted_catalog.read("recording-01") is None
    assert restarted_catalog.pending_processor_runs() == ()


def test_same_process_retry_replays_converted_outbox_before_next_write(
    tmp_path: Path, monkeypatch
) -> None:
    store, catalog = _stores(tmp_path)
    store.create(_request(), created_at="2026-09-05T10:00:00Z")
    atomic_replace_json = catalog_module.atomic_replace_json

    def interrupt_source_receipt(path, value, **kwargs):
        if Path(path).parent == catalog.sources:
            raise OSError("simulated stop after catalog receipt commit")
        return atomic_replace_json(path, value, **kwargs)

    monkeypatch.setattr(catalog_module, "atomic_replace_json", interrupt_source_receipt)
    with pytest.raises(RecordingCatalogError, match="catalog publication failed"):
        store.start("catalog-run", started_at="2026-09-05T10:01:00Z")
    monkeypatch.undo()

    store.update_progress(
        "catalog-run",
        progress=RunProgress(completed=1, total=2),
        updated_at="2026-09-05T10:02:00Z",
    )
    assert catalog.read("recording-01")["counters"] == {"processor_run:event-detection:running": 1}
    assert catalog.pending_processor_runs() == ()


def test_startup_recovery_waits_for_writer_holding_run_lock(tmp_path: Path, monkeypatch) -> None:
    writer, catalog = _stores(tmp_path)
    writer.create(_request(), created_at="2026-09-05T10:00:00Z")
    recovery, recovery_catalog = _stores(tmp_path)
    intent_written = Event()
    release_writer = Event()
    recovery_started = Event()
    recovery_done = Event()
    prepare = writer._prepare_run_catalog_intent

    def pause_after_intent(*args, **kwargs):
        result = prepare(*args, **kwargs)
        intent_written.set()
        if not release_writer.wait(timeout=5):
            raise TimeoutError("writer test was not released")
        return result

    monkeypatch.setattr(writer, "_prepare_run_catalog_intent", pause_after_intent)

    def write_transition():
        return writer.start("catalog-run", started_at="2026-09-05T10:01:00Z")

    def recover():
        recovery_started.set()
        try:
            return recovery.recover_catalog_publications()
        finally:
            recovery_done.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer_future = executor.submit(write_transition)
        assert intent_written.wait(timeout=5)
        recovery_future = executor.submit(recover)
        assert recovery_started.wait(timeout=5)
        assert recovery_done.wait(timeout=0.1) is False
        release_writer.set()
        assert writer_future.result().state.status == "running"
        assert recovery_future.result() == 1

    assert recovery_catalog.read("recording-01")["counters"] == {
        "processor_run:event-detection:running": 1
    }
    assert recovery_catalog.pending_processor_runs() == ()


def test_concurrent_recovery_rechecks_exact_intent_under_run_lock(tmp_path: Path) -> None:
    store, catalog = _stores(tmp_path)
    run, _ = store.create(_request(), created_at="2026-09-05T10:00:00Z")
    old_bytes = store.state_path(run.run_id).read_bytes()
    target = replace(run.state, status="running", started_at="2026-09-05T10:01:00Z")
    target_bytes = canonical_processor_run_state_bytes(target)
    store._prepare_run_catalog_intent(
        run.request,
        target,
        old_state_digest=hashlib.sha256(old_bytes).hexdigest(),
        target_state_bytes=target_bytes,
    )
    first, _ = _stores(tmp_path)
    second, _ = _stores(tmp_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(first.recover_catalog_publications),
            executor.submit(second.recover_catalog_publications),
        ]
        assert [future.result() for future in futures] == [1, 1]

    assert catalog.pending_processor_runs() == ()
    assert store.require(run.run_id).state.status == "queued"
    assert catalog.read("recording-01")["counters"] == {"processor_run:event-detection:queued": 1}


def test_pending_intent_snapshot_serializes_with_removal(tmp_path: Path, monkeypatch) -> None:
    store, catalog = _stores(tmp_path)
    run, _ = store.create(_request(), created_at="2026-09-05T10:00:00Z")
    old_digest = hashlib.sha256(store.state_path(run.run_id).read_bytes()).hexdigest()
    target = replace(run.state, status="running", started_at="2026-09-05T10:01:00Z")
    store._prepare_run_catalog_intent(
        run.request,
        target,
        old_state_digest=old_digest,
        target_state_bytes=canonical_processor_run_state_bytes(target),
    )
    _, remover_catalog = _stores(tmp_path)
    snapshot_reading = Event()
    release_snapshot = Event()
    removal_done = Event()
    read_required = catalog._read_required

    def pause_snapshot(path):
        if Path(path).parent == catalog.outbox:
            snapshot_reading.set()
            if not release_snapshot.wait(timeout=5):
                raise TimeoutError("snapshot test was not released")
        return read_required(path)

    monkeypatch.setattr(catalog, "_read_required", pause_snapshot)

    def snapshot():
        return catalog.pending_processor_runs()

    def remove_intent():
        try:
            remover_catalog.cancel_processor_run(
                "processor-run:catalog-run", observed_state_digest=old_digest
            )
        finally:
            removal_done.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        snapshot_future = executor.submit(snapshot)
        assert snapshot_reading.wait(timeout=5)
        removal_future = executor.submit(remove_intent)
        assert removal_done.wait(timeout=0.1) is False
        release_snapshot.set()
        snapshot_result = snapshot_future.result()
        removal_future.result()

    assert len(snapshot_result) == 1
    assert snapshot_result[0]["run_id"] == "catalog-run"
    assert remover_catalog.pending_processor_runs() == ()
    assert store.require("catalog-run").state.status == "queued"


def test_pending_intent_snapshot_serializes_with_finalize(tmp_path: Path, monkeypatch) -> None:
    writer, catalog = _stores(tmp_path)
    writer.create(_request(), created_at="2026-09-05T10:00:00Z")
    intent_written = Event()
    release_writer = Event()
    finalize_started = Event()
    snapshot_reading = Event()
    release_snapshot = Event()
    prepare = writer._prepare_run_catalog_intent
    finalize = writer._finalize_run_catalog_intent
    read_required = catalog._read_required

    def pause_after_intent(*args, **kwargs):
        result = prepare(*args, **kwargs)
        intent_written.set()
        if not release_writer.wait(timeout=5):
            raise TimeoutError("writer test was not released")
        return result

    def mark_finalize_started(run_id, state_bytes):
        finalize_started.set()
        return finalize(run_id, state_bytes)

    def pause_snapshot(path):
        if Path(path).parent == catalog.outbox:
            snapshot_reading.set()
            if not release_snapshot.wait(timeout=5):
                raise TimeoutError("snapshot test was not released")
        return read_required(path)

    monkeypatch.setattr(writer, "_prepare_run_catalog_intent", pause_after_intent)
    monkeypatch.setattr(writer, "_finalize_run_catalog_intent", mark_finalize_started)
    monkeypatch.setattr(catalog, "_read_required", pause_snapshot)

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer_future = executor.submit(
            writer.start, "catalog-run", started_at="2026-09-05T10:01:00Z"
        )
        if not intent_written.wait(timeout=5):
            raise writer_future.exception() or AssertionError("writer did not prepare an intent")
        snapshot_future = executor.submit(catalog.pending_processor_runs)
        assert snapshot_reading.wait(timeout=5)
        release_writer.set()
        assert finalize_started.wait(timeout=5)
        release_snapshot.set()
        snapshot = snapshot_future.result()
        assert writer_future.result().state.status == "running"

    assert len(snapshot) == 1
    assert snapshot[0]["run_id"] == "catalog-run"
    assert catalog.pending_processor_runs() == ()
    assert catalog.read("recording-01")["counters"] == {"processor_run:event-detection:running": 1}


def test_create_source_commit_before_index_is_recovered_by_exact_intent(
    tmp_path: Path, monkeypatch
) -> None:
    store, catalog = _stores(tmp_path)
    finalize = store._finalize_run_catalog_intent

    def interrupt_after_source_commit(_run_id: str, _state_bytes: bytes) -> None:
        raise OSError("simulated stop after source commit")

    monkeypatch.setattr(store, "_finalize_run_catalog_intent", interrupt_after_source_commit)
    with pytest.raises(OSError, match="after source commit"):
        store.create(_request())

    restarted, restarted_catalog = _stores(tmp_path)
    assert restarted_catalog.read("recording-01") is None
    assert restarted.recover_catalog_publications() == 1
    assert restarted_catalog.read("recording-01")["counters"] == {
        "processor_run:event-detection:queued": 1
    }
    assert restarted.require("catalog-run").state.status == "queued"
    assert finalize is not None


def test_state_transition_source_commit_before_index_is_recovered(
    tmp_path: Path, monkeypatch
) -> None:
    store, _ = _stores(tmp_path)
    store.create(_request(), created_at="2026-09-05T10:00:00Z")
    finalize = store._finalize_run_catalog_intent

    def interrupt_after_state_commit(_run_id: str, _state_bytes: bytes) -> None:
        raise OSError("simulated stop after run-state commit")

    monkeypatch.setattr(store, "_finalize_run_catalog_intent", interrupt_after_state_commit)
    with pytest.raises(OSError, match="after run-state commit"):
        store.start("catalog-run", started_at="2026-09-05T10:01:00Z")

    restarted, catalog = _stores(tmp_path)
    assert restarted.recover_catalog_publications() == 1
    assert restarted.require("catalog-run").state.status == "running"
    assert catalog.read("recording-01")["counters"] == {"processor_run:event-detection:running": 1}
    assert finalize is not None


def test_catalog_source_receipt_gap_replays_after_state_transition(
    tmp_path: Path, monkeypatch
) -> None:
    store, catalog = _stores(tmp_path)
    store.create(_request(), created_at="2026-09-05T10:00:00Z")
    atomic_replace_json = catalog_module.atomic_replace_json

    def interrupt_source_receipt(path, value, **kwargs):
        if Path(path).parent == catalog.sources:
            raise OSError("simulated stop after catalog receipt commit")
        return atomic_replace_json(path, value, **kwargs)

    monkeypatch.setattr(catalog_module, "atomic_replace_json", interrupt_source_receipt)
    with pytest.raises(RecordingCatalogError, match="catalog publication failed"):
        store.start("catalog-run", started_at="2026-09-05T10:01:00Z")
    monkeypatch.undo()

    restarted, restarted_catalog = _stores(tmp_path)
    assert restarted_catalog.recover_pending() == 1
    assert restarted.recover_catalog_publications() == 0
    assert restarted_catalog.read("recording-01")["counters"] == {
        "processor_run:event-detection:running": 1
    }
    assert restarted_catalog.pending_processor_runs() == ()


def test_run_catalog_read_does_not_parse_saved_requests_and_is_history_compact(
    tmp_path: Path, monkeypatch
) -> None:
    store, catalog = _stores(tmp_path)
    for index in range(10):
        store.create(_request(f"run-{index:02d}"))
    before = catalog.read("recording-01")

    def fail_request_parse(_value):
        raise AssertionError("catalog list read parsed a processor-run request")

    monkeypatch.setattr(
        "dokodetector_backend.processor_run_catalog.parse_processor_run_request_bytes",
        fail_request_parse,
    )
    after = catalog.read("recording-01")
    assert after == before
    assert after["counters"] == {"processor_run:event-detection:queued": 10}
    assert set(after["metadata"]) == set(before["metadata"])


def test_same_run_create_is_serialized_across_store_instances(tmp_path: Path) -> None:
    first, catalog = _stores(tmp_path)
    second, _ = _stores(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(first.create, _request()),
            executor.submit(second.create, _request()),
        ]
        results = [future.result() for future in futures]
    assert sorted(created for _, created in results) == [False, True]
    assert catalog.read("recording-01")["counters"] == {"processor_run:event-detection:queued": 1}


def test_tenfold_terminal_run_history_keeps_compact_catalog_projection(tmp_path: Path) -> None:
    rows = []
    for name, history_size in (("small", 1), ("large", 10)):
        store, catalog = _stores(tmp_path / name)
        store._validate_output_revisions = lambda *_args, **_kwargs: None
        for index in range(history_size):
            run_id = f"failed-{index:02d}"
            store.create(
                _request(run_id),
                created_at="2026-09-05T10:00:00Z",
            )
            store.start(run_id, started_at="2026-09-05T10:01:00Z")
            store.fail(
                run_id,
                RunFailure(code="processor_failed", message="processor failed"),
                completed_at="2026-09-05T10:02:00Z",
            )
        store.create(_request("one-active"), created_at="2026-09-05T10:03:00Z")
        store.start("one-active", started_at="2026-09-05T10:04:00Z")
        rows.append(catalog.read("recording-01"))

    small, large = rows
    assert small["counters"]["processor_run:event-detection:running"] == 1
    assert large["counters"]["processor_run:event-detection:running"] == 1
    assert small["counters"]["processor_run:event-detection:failed"] == 1
    assert large["counters"]["processor_run:event-detection:failed"] == 10
    assert set(small["counters"]) == set(large["counters"])
    assert len(json.dumps(large, sort_keys=True)) < len(json.dumps(small, sort_keys=True)) * 1.25


def test_indexed_recordings_status_does_not_read_saved_run_requests(
    tmp_path: Path, monkeypatch
) -> None:
    client, app = _backend(tmp_path, recording_catalog_test_activation=True)
    with client:
        run_request = request("indexed-active-run").to_mapping()
        run_request["source"]["recording_id"] = RECORDING_ID
        run_request["input_revision_ids"] = []
        run_request["processor_type"] = "event-detection"
        app.state.pipeline_run_store.create(run_request)
        app.state.pipeline_run_store.start("indexed-active-run")

        def fail_run_scan(_recording_ids):
            raise AssertionError("indexed recordings list scanned saved processor-run requests")

        monkeypatch.setattr(
            app.state.pipeline_workspace_service,
            "_list_statuses_for_recordings",
            fail_run_scan,
        )
        response = client.get("/v1/recordings")
        assert response.status_code == 200, response.text
        row = next(
            item for item in response.json()["recordings"] if item["recording_id"] == RECORDING_ID
        )
        stages = {stage["key"]: stage["state"] for stage in row["pipeline_status"]["stages"]}
        assert stages["events"] == "active-run"
