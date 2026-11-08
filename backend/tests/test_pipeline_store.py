from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from doko_operations.pipeline_data import (
    EventDataRevision,
    ProcessorRunRequest,
    RunFailure,
    RunItemOutcome,
    RunProgress,
    canonical_json_bytes,
    canonical_processor_run_state_bytes,
    sha256_bytes,
)

from dokodetector_backend.legacy_processor_run_store import LegacyProcessorRunStore
from dokodetector_backend.pipeline_revision_store import PipelineRevisionStore
from dokodetector_backend.pipeline_storage import (
    PipelineConflict,
    PipelineNotFound,
    PipelineRuntimeStorage,
    PipelineStateError,
    PipelineStoreError,
)
from dokodetector_backend.processor_run_store import ProcessorRunStore

DIGEST = "a" * 64
SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": DIGEST,
    "byte_length": 100,
    "duration_us": 10_000_000,
}


def event_content(*, with_score: bool = False) -> dict[str, object]:
    event: dict[str, object] = {
        "event_id": "event-01",
        "event_type": "card_state_changed",
        "start_us": 1_000_000,
        "end_us": 1_250_000,
    }
    if with_score:
        event["model_scores"] = [{"producer_id": "card-event-net.v1", "score": 0.75}]
    return {"schema_version": "event-data/v1", "events": [event]}


def manifest(
    *,
    revision_id: str,
    producer: dict[str, object],
    origin: str = "processor",
    input_revision_ids: list[str] | None = None,
    source: dict[str, object] | None = None,
    content: dict[str, object] | None = None,
) -> dict[str, object]:
    source = json.loads(json.dumps(SOURCE if source is None else source))
    content = event_content(with_score=origin == "processor") if content is None else content
    result: dict[str, object] = {
        "schema_version": "data-revision/v1",
        "revision_id": revision_id,
        "content_type": "events",
        "content_schema": "event-data/v1",
        "recording_id": source["recording_id"],
        "source": source,
        "content_sha256": sha256_bytes(canonical_json_bytes(content)),
        "input_revision_ids": [] if input_revision_ids is None else input_revision_ids,
        "origin": origin,
        "producer": producer,
        "coverage": {"kind": "processed", "intervals": []},
        "created_at": "2026-09-05T10:00:00Z",
    }
    return result


def revision(
    *,
    revision_id: str,
    producer: dict[str, object],
    origin: str = "processor",
    input_revision_ids: list[str] | None = None,
    content: dict[str, object] | None = None,
) -> EventDataRevision:
    content = event_content(with_score=origin == "processor") if content is None else content
    return EventDataRevision.from_mapping(
        {
            "manifest": manifest(
                revision_id=revision_id,
                producer=producer,
                origin=origin,
                input_revision_ids=input_revision_ids,
                content=content,
            ),
            "content": content,
        }
    )


def processor_producer(run_id: str) -> dict[str, object]:
    return {
        "kind": "processor",
        "processor_type": "event-detection",
        "run_id": run_id,
        "implementation_id": "event-worker.v1",
        "model_id": "card-event-net/v2",
    }


def request(run_id: str = "run-01") -> ProcessorRunRequest:
    return ProcessorRunRequest.from_mapping(
        {
            "schema_version": "processor-run-request/v1",
            "run_id": run_id,
            "processor_type": "event-detection",
            "source": SOURCE,
            "input_revision_ids": ["revision-input"],
            "implementation": {"name": "event-worker", "version": "1"},
            "model": {
                "name": "card-event-net",
                "version": "2",
                "weights_sha256": DIGEST,
                "preprocessing": "full-frame/v1",
            },
            "configuration": {"threshold": 0.5, "labels": ["card_state_changed"]},
            "extraction_policy": {"policy_id": "exact-event/v1", "boundary": "nearest"},
            "crop_policy": None,
        }
    )


def test_revision_store_is_restartable_idempotent_and_deterministic(tmp_path: Path) -> None:
    store = PipelineRevisionStore(tmp_path / "runtime")
    base = revision(revision_id="revision-input", producer=processor_producer("import-01"))
    stored, created = store.publish(base)
    replay, replay_created = store.publish(base)

    assert created is True
    assert replay_created is False
    assert replay == stored
    assert store.revision_path("revision-input").relative_to(tmp_path).as_posix() == (
        "runtime/pipeline/revisions/revision-input"
    )
    assert PipelineRevisionStore(tmp_path / "runtime").list() == (stored,)

    changed_content = event_content(with_score=True)
    changed_content["events"][0]["end_us"] = 1_500_000  # type: ignore[index]
    changed = revision(
        revision_id="revision-input",
        producer=processor_producer("import-01"),
        content=changed_content,
    )
    with pytest.raises(PipelineConflict):
        store.publish(changed)


def test_revision_store_requires_published_lineage_and_reports_invalid_entries(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = PipelineRevisionStore(tmp_path / "runtime")
    child = revision(
        revision_id="revision-child",
        producer=processor_producer("run-01"),
        input_revision_ids=["missing-input"],
    )
    with pytest.raises(PipelineNotFound):
        store.publish(child)

    dangling = store.revision_path("revision-child")
    dangling.mkdir(parents=True)
    (dangling / "manifest.json").write_bytes(canonical_json_bytes(child.manifest.to_mapping()))
    (dangling / "content.json").write_bytes(canonical_json_bytes(child.content.to_mapping()))
    invalid = store.root / "invalid"
    invalid.mkdir(parents=True)
    (invalid / "manifest.json").write_text("{}", encoding="utf-8")
    staging = store.root / ".abandoned-staging"
    staging.mkdir()
    assert store.list() == ()
    assert "pipeline_revision_catalog_skipped" in caplog.text


def test_revision_store_rejects_content_changed_after_publication(tmp_path: Path) -> None:
    store = PipelineRevisionStore(tmp_path / "runtime")
    saved, _ = store.publish(
        revision(revision_id="revision-tampered", producer=processor_producer("import-01"))
    )
    path = store.revision_path(saved.manifest.revision_id) / "content.json"
    content = json.loads(path.read_text(encoding="utf-8"))
    content["events"][0]["event_id"] = "changed-event"
    path.write_bytes(canonical_json_bytes(content))

    assert store.get(saved.manifest.revision_id) is None
    assert PipelineRevisionStore(tmp_path / "runtime").get(saved.manifest.revision_id) is None


def test_pipeline_catalogs_filter_by_recording(tmp_path: Path) -> None:
    store = PipelineRevisionStore(tmp_path / "runtime")
    first = revision(revision_id="revision-first", producer=processor_producer("import-first"))
    other_source = dict(SOURCE)
    other_source["recording_id"] = "recording-02"
    other = EventDataRevision.from_mapping(
        {
            "manifest": manifest(
                revision_id="revision-other",
                producer=processor_producer("import-other"),
                source=other_source,
            ),
            "content": event_content(with_score=True),
        }
    )
    first_stored, _ = store.publish(first)
    store.publish(other)

    run_store = ProcessorRunStore(tmp_path / "runtime")
    first_request = request("run-first")
    other_request = ProcessorRunRequest.from_mapping(
        {**first_request.to_mapping(), "run_id": "run-other", "source": other_source}
    )
    run_store.create(first_request)
    run_store.create(other_request)

    assert store.list_for_recording("recording-01") == (first_stored,)
    assert [run.run_id for run in run_store.list_for_recording("recording-01")] == ["run-first"]


def test_run_store_publishes_request_and_state_together_and_supports_retry(tmp_path: Path) -> None:
    revision_store = PipelineRevisionStore(tmp_path / "runtime")
    input_revision = revision(
        revision_id="revision-input",
        producer=processor_producer("import-01"),
    )
    revision_store.publish(input_revision)
    run_store = ProcessorRunStore(PipelineRuntimeStorage(tmp_path / "runtime"))

    stored, created = run_store.create(request(), created_at="2026-09-05T10:00:00Z")
    assert created is True
    assert stored.state.status == "queued"
    assert ProcessorRunStore(tmp_path / "runtime").get("run-01") == stored

    running = run_store.start("run-01", started_at="2026-09-05T10:01:00Z")
    failed_item = RunItemOutcome(
        item_id="event-01",
        status="failed",
        result=None,
        failure=RunFailure(code="decode_failed", message="frame unavailable"),
    )
    partial = run_store.partial(
        "run-01",
        progress=RunProgress(completed=0, total=1),
        items=(failed_item,),
        completed_at="2026-09-05T10:02:00Z",
    )
    retried = run_store.retry("run-01", started_at="2026-09-05T10:03:00Z")

    assert running.state.status == "running"
    assert partial.state.status == "partial"
    assert retried.state.attempt == 2
    assert retried.state.items == (failed_item,)
    assert retried.request == request()
    assert run_store.request_path("run-01").read_bytes() == canonical_json_bytes(
        request().to_mapping()
    )


def test_legacy_state_without_metrics_is_read_only_by_migration_store(tmp_path: Path) -> None:
    revision_store = PipelineRevisionStore(tmp_path / "runtime")
    runtime_store = ProcessorRunStore(tmp_path / "runtime")
    stored, _ = runtime_store.create(request())
    legacy_state = stored.state.to_mapping()
    legacy_state["schema_version"] = "processor-run-state/v1"
    legacy_state.pop("metrics")
    runtime_store.items_path("run-01").rmdir()
    runtime_store.state_path("run-01").write_bytes(canonical_json_bytes(legacy_state))

    assert runtime_store.get("run-01") is None
    migration_store = LegacyProcessorRunStore(tmp_path / "runtime", revision_store=revision_store)
    loaded = migration_store.require("run-01")

    assert loaded.state.metrics == {}
    assert migration_store.list() == (loaded,)


def test_catalog_does_not_warn_for_retired_single_file_run_state(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    run_store = ProcessorRunStore(tmp_path / "runtime")
    stored, _ = run_store.create(request())
    run_store.items_path("run-01").rmdir()
    run_store.state_path("run-01").write_bytes(canonical_processor_run_state_bytes(stored.state))

    with caplog.at_level("WARNING"):
        assert run_store.list_statuses() == ()

    assert "processor_run_catalog_skipped" not in caplog.text


def test_processor_run_store_splits_item_outcomes_on_disk(tmp_path: Path) -> None:
    run_store = ProcessorRunStore(tmp_path / "runtime")
    run_store.create(request())
    run_store.start("run-01")
    item = RunItemOutcome(
        item_id="event-01",
        status="failed",
        result=None,
        failure=RunFailure(code="decode_failed", message="frame unavailable"),
    )

    run_store.record_item_progress(
        "run-01",
        progress=RunProgress(completed=1, total=1),
        item=item,
    )

    state_document = json.loads(run_store.state_path("run-01").read_text(encoding="utf-8"))
    assert state_document["item_ids"] == ["event-01"]
    assert "items" not in state_document
    item_path = run_store.items_path("run-01") / "event-01.json"
    assert item_path.is_file()
    stored = run_store.require("run-01")
    assert stored.state.items == (item,)
    metadata = stored.state.to_mapping()
    metadata.pop("items")
    metadata["item_ids"] = ["event-01"]
    assert run_store.state_path("run-01").read_bytes() == canonical_json_bytes(metadata)
    assert item_path.read_bytes() == canonical_json_bytes(item.to_mapping())


def test_processor_run_store_can_read_split_metadata_without_items(
    tmp_path: Path,
) -> None:
    run_store = ProcessorRunStore(tmp_path / "runtime")
    run_store.create(request())
    run_store.start("run-01")
    run_store.record_item_progress(
        "run-01",
        progress=RunProgress(completed=1, total=1),
        item=RunItemOutcome(
            item_id="event-01",
            status="succeeded",
            result={"event_type": "card_state_changed"},
            failure=None,
        ),
    )

    loaded = run_store.require("run-01", include_items=False)

    assert loaded.state.items == ()
    assert loaded.state.progress == RunProgress(completed=1, total=1)


def test_list_statuses_does_not_walk_item_files(tmp_path: Path, monkeypatch) -> None:
    run_store = ProcessorRunStore(tmp_path / "runtime")
    run_store.create(request())
    run_store.start("run-01")
    run_store.record_item_progress(
        "run-01",
        progress=RunProgress(completed=1, total=1),
        item=RunItemOutcome(
            item_id="event-01",
            status="succeeded",
            result={"event_type": "card_state_changed"},
            failure=None,
        ),
    )

    def fail_rglob(self, pattern):  # noqa: ANN001
        del pattern
        raise AssertionError(f"list_statuses must not rglob {self}")

    monkeypatch.setattr(Path, "rglob", fail_rglob)

    statuses = run_store.list_statuses()
    assert len(statuses) == 1
    assert statuses[0].run_id == "run-01"
    assert statuses[0].status == "running"


def test_restart_recovery_uses_compact_status_catalog(tmp_path: Path, monkeypatch) -> None:
    run_store = ProcessorRunStore(tmp_path / "runtime")
    run_store.create(request())
    run_store.start("run-01")

    def fail_full_catalog():
        raise AssertionError("restart recovery must not load every retained run")

    monkeypatch.setattr(run_store, "list", fail_full_catalog)

    converted = run_store.fail_non_terminal(
        failure=RunFailure(code="backend_restarted", message="backend restarted")
    )

    assert converted == 1
    assert run_store.require("run-01").state.status == "failed"


def test_catalog_read_does_not_walk_item_files(tmp_path: Path, monkeypatch) -> None:
    run_store = ProcessorRunStore(tmp_path / "runtime")
    run_store.create(request())
    run_store.start("run-01")
    for index in range(50):
        run_store.record_item_progress(
            "run-01",
            progress=RunProgress(completed=index + 1, total=50),
            item=RunItemOutcome(
                item_id=f"event-{index:02d}",
                status="succeeded",
                result={"event_type": "card_state_changed"},
                failure=None,
            ),
        )

    def fail_rglob(self, pattern):  # noqa: ANN001
        del pattern
        raise AssertionError(f"catalog read must not rglob {self}")

    monkeypatch.setattr(Path, "rglob", fail_rglob)

    loaded = run_store.require("run-01", include_items=False)
    listed = run_store.list_for_recording("recording-01", include_items=False)

    assert loaded.state.items == ()
    assert loaded.state.progress == RunProgress(completed=50, total=50)
    assert [run.run_id for run in listed] == ["run-01"]
    assert listed[0].state.items == ()


def test_revision_store_has_revision_without_reading_content(tmp_path: Path) -> None:
    revision_store = PipelineRevisionStore(tmp_path / "runtime")
    published = revision(revision_id="revision-input", producer=processor_producer("import-01"))
    revision_store.publish(published)

    assert revision_store.has_revision("revision-input") is True
    assert revision_store.has_revision("missing-revision") is False


def test_run_store_ignores_removed_atomic_state_temp_files_during_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_store = ProcessorRunStore(tmp_path / "runtime")
    run_store.create(request())
    run_path = run_store.run_path("run-01")
    removed_temp_path = run_path / ".state.json.removed.tmp"
    original_rglob = Path.rglob

    def rglob_with_stale_temp(path: Path, pattern: str):
        members = list(original_rglob(path, pattern))
        if path == run_path:
            members.append(removed_temp_path)
        return iter(members)

    monkeypatch.setattr(Path, "rglob", rglob_with_stale_temp)

    assert run_store.get("run-01") is not None
    assert [item.run_id for item in run_store.list_statuses()] == ["run-01"]


def test_run_store_requires_published_output_and_rejects_illegal_transition(tmp_path: Path) -> None:
    revision_store = PipelineRevisionStore(tmp_path / "runtime")
    revision_store.publish(
        revision(
            revision_id="revision-input",
            producer=processor_producer("import-01"),
        )
    )
    run_store = LegacyProcessorRunStore(tmp_path / "runtime", revision_store=revision_store)
    run_store.create(request())
    run_store.start("run-01")

    with pytest.raises(PipelineStoreError):
        run_store.complete("run-01", ["not-published"])

    with pytest.raises(PipelineStateError):
        run_store.update_state(
            "run-01",
            replace(run_store.require("run-01").state, status="queued"),
        )

    output = revision(
        revision_id="revision-output",
        producer=processor_producer("run-01"),
        input_revision_ids=["revision-input"],
    )
    revision_store.publish(output)
    complete = run_store.complete("run-01", ["revision-output"])
    assert complete.state.status == "complete"
    assert complete.state.output_revision_ids == ("revision-output",)


def test_run_store_does_not_read_outputs_from_legacy_revision_storage(tmp_path: Path) -> None:
    revision_store = PipelineRevisionStore(tmp_path / "runtime")
    revision_store.publish(
        revision(
            revision_id="revision-output",
            producer=processor_producer("run-01"),
        )
    )
    run_store = ProcessorRunStore(tmp_path / "runtime")
    run_store.create(request())
    run_store.start("run-01")

    with pytest.raises(PipelineStateError, match="lineage writer"):
        run_store.complete("run-01", ["revision-output"])


def test_run_catalog_skips_run_with_unpublished_output_revision(tmp_path: Path) -> None:
    revision_store = PipelineRevisionStore(tmp_path / "runtime")
    revision_store.publish(
        revision(
            revision_id="revision-input",
            producer=processor_producer("import-01"),
        )
    )
    run_store = LegacyProcessorRunStore(tmp_path / "runtime", revision_store=revision_store)
    run_store.create(request())
    running = run_store.start("run-01")

    corrupted_state = replace(
        running.state,
        status="complete",
        completed_at=running.state.updated_at,
        output_revision_ids=("revision-invalid",),
    )
    run_store.state_path("run-01").write_bytes(canonical_processor_run_state_bytes(corrupted_state))

    assert run_store.list() == ()
    assert (
        run_store.fail_non_terminal(
            failure=RunFailure(code="backend_restarted", message="backend restarted")
        )
        == 0
    )


def test_run_store_file_lock_serializes_independent_store_instances(tmp_path: Path) -> None:
    stores = [ProcessorRunStore(tmp_path / "runtime") for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda store: store.create(request()), stores))

    assert sorted(created for _, created in results) == [False, True]
    assert results[0][0] == results[1][0]
    assert len(stores[0].list()) == 1


def test_run_store_rejects_corrupted_item_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    run_store = ProcessorRunStore(tmp_path / "runtime")
    run_store.create(request())
    run_store.start("run-01")
    run_store.record_item_progress(
        "run-01",
        progress=RunProgress(completed=1, total=1),
        item=RunItemOutcome(
            item_id="event-01",
            status="succeeded",
            result={"event_type": "card_state_changed"},
            failure=None,
        ),
    )
    (run_store.items_path("run-01") / "event-01.json").write_bytes(b"{}")

    assert run_store.get("run-01") is None
    assert "processor_run_catalog_skipped" in caplog.text
