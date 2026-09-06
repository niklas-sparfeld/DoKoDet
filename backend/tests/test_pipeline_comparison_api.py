from __future__ import annotations

from pathlib import Path
from typing import Any

from app_factory import create_test_app
from doko_operations.pipeline_data import (
    DataRevision,
    EventData,
    HumanProducer,
    ProcessorProducer,
    ProcessorRunRequest,
    RecordingVideoSource,
    RunProgress,
    canonical_event_data_bytes,
    sha256_bytes,
)
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings
from dokodetector_backend.pipeline_store import PipelineRevisionStore, ProcessorRunStore

RECORDING_ID = "recording-1"
VIDEO_DIGEST = "a" * 64
SOURCE = RecordingVideoSource(
    recording_id=RECORDING_ID,
    relative_path="recordings/recording-1/video.mov",
    video_sha256=VIDEO_DIGEST,
    byte_length=100,
    duration_us=2_000_000,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        repository_root=tmp_path,
        evidence_root=tmp_path / "runtime",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "evidence-packages",
        pending_video_root=tmp_path / "pending-videos",
    )


def _content(events: list[dict[str, Any]]) -> EventData:
    return EventData.from_mapping({"schema_version": "event-data/v1", "events": events})


def _publish_revision(
    revisions: PipelineRevisionStore,
    *,
    revision_id: str,
    content: EventData,
    origin: str,
    run_id: str | None = None,
    input_revision_ids: list[str] | None = None,
    coverage: dict[str, Any] | None = None,
) -> None:
    producer: Any = (
        ProcessorProducer(
            run_id=run_id or "fixture-import",
            processor_type="event-detection",
            implementation_id="fixture.v1",
        )
        if origin == "processor"
        else HumanProducer(review_id="review-1", operator_id="operator-1")
    )
    manifest = DataRevision(
        revision_id=revision_id,
        content_type="events",
        content_schema="event-data/v1",
        recording_id=RECORDING_ID,
        source=SOURCE,
        content_sha256=sha256_bytes(canonical_event_data_bytes(content)),
        input_revision_ids=tuple(input_revision_ids or ()),
        origin=origin,
        producer=producer,
        coverage=coverage or {"kind": "full-recording"},
        created_at="2026-09-06T10:00:00Z",
    )
    revisions.publish(manifest, content)


def _create_complete_run(
    runs: ProcessorRunStore,
    revisions: PipelineRevisionStore,
    *,
    run_id: str,
    revision_id: str,
    content: EventData,
    input_revision_ids: list[str] | None = None,
    extraction_policy: dict[str, Any] | None = None,
) -> None:
    request = ProcessorRunRequest.from_mapping(
        {
            "schema_version": "processor-run-request/v1",
            "run_id": run_id,
            "processor_type": "event-detection",
            "source": SOURCE.to_mapping(),
            "input_revision_ids": input_revision_ids or [],
            "implementation": {"name": "fixture", "version": run_id},
            "configuration": {"threshold": 0.5},
            "extraction_policy": extraction_policy or {"policy_id": "event-extract/v1"},
            "crop_policy": None,
        }
    )
    runs.create(request, created_at="2026-09-06T10:00:00Z")
    runs.start(run_id, started_at="2026-09-06T10:00:01Z")
    _publish_revision(
        revisions,
        revision_id=revision_id,
        content=content,
        origin="processor",
        run_id=run_id,
        input_revision_ids=input_revision_ids,
    )
    runs.complete(run_id, [revision_id], completed_at="2026-09-06T10:00:02Z")


def _create_partial_run(
    runs: ProcessorRunStore,
    revisions: PipelineRevisionStore,
    *,
    run_id: str,
    revision_id: str,
    content: EventData,
) -> None:
    request = ProcessorRunRequest.from_mapping(
        {
            "schema_version": "processor-run-request/v1",
            "run_id": run_id,
            "processor_type": "event-detection",
            "source": SOURCE.to_mapping(),
            "input_revision_ids": [],
            "implementation": {"name": "fixture", "version": run_id},
            "configuration": {"threshold": 0.5},
            "extraction_policy": {"policy_id": "event-extract/v1"},
            "crop_policy": None,
        }
    )
    runs.create(request, created_at="2026-09-06T10:00:00Z")
    runs.start(run_id, started_at="2026-09-06T10:00:01Z")
    _publish_revision(
        revisions,
        revision_id=revision_id,
        content=content,
        origin="processor",
        run_id=run_id,
    )
    runs.partial(
        run_id,
        progress=RunProgress(completed=0, total=1),
        items=(),
        output_revision_ids=[revision_id],
        completed_at="2026-09-06T10:00:02Z",
    )


def _request(left: str, right: str, reference: str) -> dict[str, Any]:
    return {
        "schema_version": "pipeline-comparison-request/v1",
        "recording_id": RECORDING_ID,
        "content_type": "events",
        "left_run_id": left,
        "right_run_id": right,
        "reference_revision_id": reference,
        "matching_policy": {
            "policy_id": "event-timing/v1",
            "anchor": "start_us",
            "tolerance_us": 50_000,
        },
    }


def test_event_comparison_is_deterministic_and_reports_review_scope(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_test_app(settings)
    revisions = app.state.pipeline_revision_store
    runs = app.state.pipeline_run_store
    reference_content = _content(
        [
            {
                "event_id": "ref-1",
                "event_type": "card_played",
                "start_us": 500_000,
                "end_us": 510_000,
            },
            {
                "event_id": "ref-2",
                "event_type": "card_played",
                "start_us": 1_500_000,
                "end_us": 1_510_000,
            },
        ]
    )
    _publish_revision(
        revisions,
        revision_id="reference-1",
        content=reference_content,
        origin="manual",
        coverage={"kind": "event_intervals", "intervals": [{"start_us": 0, "end_us": 1_000_000}]},
    )
    _create_complete_run(
        runs,
        revisions,
        run_id="left-run",
        revision_id="left-output",
        content=_content(
            [
                {
                    "event_id": "left-match",
                    "event_type": "card_played",
                    "start_us": 510_000,
                    "end_us": 520_000,
                },
                {
                    "event_id": "left-extra",
                    "event_type": "card_played",
                    "start_us": 700_000,
                    "end_us": 710_000,
                },
                {
                    "event_id": "left-unreviewed",
                    "event_type": "card_played",
                    "start_us": 1_500_000,
                    "end_us": 1_510_000,
                },
            ]
        ),
    )
    _create_complete_run(
        runs,
        revisions,
        run_id="right-run",
        revision_id="right-output",
        content=_content(
            [
                {
                    "event_id": "right-match",
                    "event_type": "card_played",
                    "start_us": 500_000,
                    "end_us": 510_000,
                }
            ]
        ),
    )

    with TestClient(app) as client:
        first = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/comparisons",
            json=_request("left-run", "right-run", "reference-1"),
        )
        second = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/comparisons",
            json=_request("left-run", "right-run", "reference-1"),
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == second.content
    body = first.json()
    assert body["mode"] == "paired_processor"
    assert body["paired_delta"] is not None
    assert body["scope"]["reviewed"] == [{"start_us": 0, "end_us": 1_000_000}]
    assert body["counts"]["left"] == {
        "reference_events": 1,
        "run_events": 2,
        "matches": 1,
        "misses": 0,
        "extras": 1,
        "not_reviewed": 1,
        "unpaired_input": 0,
        "failures": 0,
    }
    assert {item["outcome"] for item in body["items"]} == {"match", "extra", "not_reviewed"}


def test_changed_upstream_input_has_no_paired_delta(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    revisions = app.state.pipeline_revision_store
    runs = app.state.pipeline_run_store
    base = _content([])
    _publish_revision(revisions, revision_id="upstream-1", content=base, origin="manual")
    reference = _content(
        [{"event_id": "ref-1", "event_type": "card_played", "start_us": 500_000, "end_us": 510_000}]
    )
    _publish_revision(revisions, revision_id="reference-1", content=reference, origin="manual")
    _create_complete_run(
        runs,
        revisions,
        run_id="left-run",
        revision_id="left-output",
        content=reference,
    )
    _create_complete_run(
        runs,
        revisions,
        run_id="right-run",
        revision_id="right-output",
        content=reference,
        input_revision_ids=["upstream-1"],
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/comparisons",
            json=_request("left-run", "right-run", "reference-1"),
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "upstream_experiment"
    assert response.json()["paired_delta"] is None


def test_partial_run_with_valid_output_is_comparable(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    revisions = app.state.pipeline_revision_store
    runs = app.state.pipeline_run_store
    reference = _content(
        [{"event_id": "ref-1", "event_type": "card_played", "start_us": 500_000, "end_us": 510_000}]
    )
    _publish_revision(revisions, revision_id="reference-1", content=reference, origin="manual")
    _create_partial_run(
        runs,
        revisions,
        run_id="partial-run",
        revision_id="partial-output",
        content=reference,
    )
    _create_complete_run(
        runs,
        revisions,
        run_id="complete-run",
        revision_id="complete-output",
        content=reference,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/comparisons",
            json=_request("partial-run", "complete-run", "reference-1"),
        )

    assert response.status_code == 200
    assert response.json()["left"]["status"] == "partial"


def test_failed_run_is_not_selectable_for_comparison(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    runs = app.state.pipeline_run_store
    request = ProcessorRunRequest.from_mapping(
        {
            "schema_version": "processor-run-request/v1",
            "run_id": "failed-run",
            "processor_type": "event-detection",
            "source": SOURCE.to_mapping(),
            "input_revision_ids": [],
            "implementation": {"name": "fixture", "version": "failed"},
            "configuration": {},
            "extraction_policy": {"policy_id": "event-extract/v1"},
            "crop_policy": None,
        }
    )
    runs.create(request)
    runs.start("failed-run")
    runs.fail("failed-run", {"code": "decode_failed", "message": "fixture failure"})

    with TestClient(app) as client:
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/comparisons",
            json=_request("failed-run", "other-run", "reference-1"),
        )

    assert response.status_code == 404 or response.status_code == 422
