from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from doko_operations.pipeline_data import (
    EventDataRevision,
    PipelineSelectionUpdate,
    ProcessorRunRequest,
    RunFailure,
    RunItemOutcome,
    RunProgress,
    canonical_json_bytes,
    canonical_processor_run_state_bytes,
    sha256_bytes,
)

from dokodetector_backend.pipeline_store import (
    PipelineConflict,
    PipelineNotFound,
    PipelineRevisionStore,
    PipelineRuntimeStorage,
    PipelineSelectionConflict,
    PipelineSelectionStore,
    PipelineStateError,
    PipelineStoreError,
    ProcessorRunStore,
)

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

    run_store = ProcessorRunStore(tmp_path / "runtime", revision_store=store)
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
    run_store = ProcessorRunStore(
        PipelineRuntimeStorage(tmp_path / "runtime"), revision_store=revision_store
    )

    stored, created = run_store.create(request(), created_at="2026-09-05T10:00:00Z")
    assert created is True
    assert stored.state.status == "queued"
    assert (
        ProcessorRunStore(tmp_path / "runtime", revision_store=revision_store).get("run-01")
        == stored
    )

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


def test_run_store_requires_published_output_and_rejects_illegal_transition(tmp_path: Path) -> None:
    revision_store = PipelineRevisionStore(tmp_path / "runtime")
    revision_store.publish(
        revision(
            revision_id="revision-input",
            producer=processor_producer("import-01"),
        )
    )
    run_store = ProcessorRunStore(tmp_path / "runtime", revision_store=revision_store)
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


def test_run_catalog_skips_run_with_unpublished_output_revision(tmp_path: Path) -> None:
    revision_store = PipelineRevisionStore(tmp_path / "runtime")
    revision_store.publish(
        revision(
            revision_id="revision-input",
            producer=processor_producer("import-01"),
        )
    )
    run_store = ProcessorRunStore(tmp_path / "runtime", revision_store=revision_store)
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


def test_selection_store_validates_roles_and_optimistic_updates(tmp_path: Path) -> None:
    revision_store = PipelineRevisionStore(tmp_path / "runtime")
    revision_store.publish(
        revision(
            revision_id="revision-input",
            producer=processor_producer("import-01"),
        )
    )
    run_store = ProcessorRunStore(tmp_path / "runtime", revision_store=revision_store)
    run_store.create(request())
    run_store.start("run-01")
    revision_store.publish(
        revision(
            revision_id="revision-output",
            producer=processor_producer("run-01"),
            input_revision_ids=["revision-input"],
        )
    )
    run_store.complete("run-01", ["revision-output"])
    human_content = event_content(with_score=False)
    human = revision(
        revision_id="revision-human",
        producer={"kind": "human", "review_id": "review-01", "operator_id": "operator-01"},
        origin="manual",
        content=human_content,
    )
    revision_store.publish(human)
    selections = PipelineSelectionStore(
        tmp_path / "runtime", revision_store=revision_store, run_store=run_store
    )

    selected = selections.update(
        "recording-01",
        "events",
        PipelineSelectionUpdate(
            expected_revision=0,
            selected_generated_revision_id="revision-output",
            selected_completed_reference_revision_id="revision-human",
        ),
        updated_at="2026-09-05T10:05:00Z",
    )
    assert selected.revision == 1
    assert selections.list_for_recording("recording-01") == (selected,)
    with pytest.raises(PipelineSelectionConflict):
        selections.update(
            "recording-01",
            "events",
            PipelineSelectionUpdate(
                expected_revision=0,
                selected_generated_revision_id=None,
                selected_completed_reference_revision_id=None,
            ),
        )

    with pytest.raises(PipelineStateError):
        selections.update(
            "recording-01",
            "events",
            PipelineSelectionUpdate(
                expected_revision=1,
                selected_generated_revision_id="revision-human",
                selected_completed_reference_revision_id=None,
            ),
        )


def test_atomic_selection_failure_keeps_previous_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PipelineSelectionStore(tmp_path / "runtime")
    store.update_pointers(
        "recording-01",
        "events",
        expected_revision=0,
        selected_generated_revision_id=None,
        selected_completed_reference_revision_id=None,
    )
    path = store.selection_path("recording-01", "events")
    before = path.read_bytes()

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated selection replacement failure")

    monkeypatch.setattr("dokodetector_backend.pipeline_store.atomic_replace_json", fail_replace)
    with pytest.raises(OSError, match="simulated selection replacement failure"):
        store.update_pointers(
            "recording-01",
            "events",
            expected_revision=1,
            selected_generated_revision_id=None,
            selected_completed_reference_revision_id=None,
        )
    assert path.read_bytes() == before
