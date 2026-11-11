from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app_factory import create_test_app
from doko_operations.pipeline_data import (
    EventData,
    ProcessorRunRequest,
    RecordingVideoSource,
    RunProgress,
)
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings
from dokodetector_backend.processor_run_store import ProcessorRunStore
from dokodetector_backend.recording_folder_store import RecordingFolderStore

RECORDING_ID = "recording-both"
VIDEO_DIGEST = "7184fd89dd78b265e8f617989e8a9659897e060bde2d4f8d47dc05708771f8a8"
SOURCE = RecordingVideoSource(
    recording_id=RECORDING_ID,
    relative_path="recordings/recording-both/video.mov",
    video_sha256=VIDEO_DIGEST,
    byte_length=55,
    duration_us=2_000_000,
)


def _settings(tmp_path: Path) -> Settings:
    bundle = Path(__file__).parents[2] / "fixtures/repository-bundle/v1/both"
    transport = tmp_path / "transport" / RECORDING_ID
    shutil.copytree(bundle, transport)
    RecordingFolderStore(tmp_path / "recordings").publish_bundle(
        transport, recording_id=RECORDING_ID
    )
    return Settings(
        _env_file=None,
        repository_root=tmp_path,
        evidence_root=tmp_path / "runtime",
        repository_intake_root=tmp_path / "recordings",
        recordings_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "evidence-packages",
        pending_video_root=tmp_path / "pending-videos",
    )


def _content(events: list[dict[str, Any]]) -> EventData:
    return EventData.from_mapping({"schema_version": "event-data/v1", "events": events})


def _publish_revision(
    app: Any,
    *,
    revision_id: str,
    content: EventData,
    origin: str,
    run_id: str | None = None,
    input_revision_ids: list[str] | None = None,
    coverage: dict[str, Any] | None = None,
):
    set_id = f"run-{revision_id}" if origin == "processor" else revision_id
    stored = app.state.event_set_store.save(
        RECORDING_ID,
        set_id=set_id,
        version="1",
        content=content.to_mapping(),
        origin=origin,
        provenance={"source": {"recording_id": RECORDING_ID, "video_sha256": VIDEO_DIGEST}},
    )
    stored = app.state.event_set_store.get(RECORDING_ID, set_id, "1")
    assert stored is not None
    if coverage is not None:
        app.state.event_set_store.save_review(
            RECORDING_ID,
            set_id,
            "1",
            review_id=f"coverage-{revision_id}",
            kind="coverage",
            question="Which interval was reviewed?",
            decision=None,
            reviewer={"operator_id": "operator-1"},
            evidence={"source": "comparison fixture"},
            coverage=coverage,
        )
    return stored


def _create_complete_run(
    runs: ProcessorRunStore,
    app: Any,
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
    _publish_revision(app, revision_id=run_id, content=content, origin="processor", run_id=run_id)
    runs.complete(run_id, [], completed_at="2026-09-06T10:00:02Z")


def _create_partial_run(
    runs: ProcessorRunStore,
    app: Any,
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
    _publish_revision(app, revision_id=run_id, content=content, origin="processor", run_id=run_id)
    runs.partial(
        run_id,
        progress=RunProgress(completed=0, total=1),
        items=(),
        output_revision_ids=[],
        completed_at="2026-09-06T10:00:02Z",
    )


def _request(left: str, right: str, reference: dict[str, str]) -> dict[str, Any]:
    return {
        "schema_version": "pipeline-comparison-request/v1",
        "recording_id": RECORDING_ID,
        "content_type": "events",
        "left_run_id": left,
        "right_run_id": right,
        "reference_revision_id": None,
        "reference_event_set_ref": reference,
        "matching_policy": {
            "policy_id": "event-timing/v1",
            "anchor": "start_us",
            "tolerance_us": 50_000,
        },
    }


def _event_set_ref(event_set: dict[str, Any]) -> dict[str, str]:
    return {
        "set_id": event_set["set_id"],
        "version": event_set["version"],
        "content_sha256": event_set["content_sha256"],
    }


def test_event_comparison_is_deterministic_and_reports_review_scope(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_test_app(settings)
    runs = app.state.pipeline_run_store
    reference_content = _content(
        [
            {
                "event_id": "ref-1",
                "event_type": "card_state_changed",
                "start_us": 500_000,
                "end_us": 510_000,
            },
            {
                "event_id": "ref-2",
                "event_type": "card_state_changed",
                "start_us": 1_500_000,
                "end_us": 1_510_000,
            },
        ]
    )
    reference_set = _publish_revision(
        app,
        revision_id="reference-1",
        content=reference_content,
        origin="manual",
        coverage={"kind": "event_intervals", "intervals": [{"start_us": 0, "end_us": 1_000_000}]},
    )
    _create_complete_run(
        runs,
        app,
        run_id="left-run",
        revision_id="left-output",
        content=_content(
            [
                {
                    "event_id": "left-match",
                    "event_type": "card_state_changed",
                    "start_us": 510_000,
                    "end_us": 520_000,
                },
                {
                    "event_id": "left-extra",
                    "event_type": "card_state_changed",
                    "start_us": 700_000,
                    "end_us": 710_000,
                },
                {
                    "event_id": "left-unreviewed",
                    "event_type": "card_state_changed",
                    "start_us": 1_500_000,
                    "end_us": 1_510_000,
                },
            ]
        ),
    )
    _create_complete_run(
        runs,
        app,
        run_id="right-run",
        revision_id="right-output",
        content=_content(
            [
                {
                    "event_id": "right-match",
                    "event_type": "card_state_changed",
                    "start_us": 500_000,
                    "end_us": 510_000,
                }
            ]
        ),
    )

    direct = app.state.pipeline_comparison_service.compare(
        RECORDING_ID,
        _request("left-run", "right-run", _event_set_ref(reference_set)),
    )
    assert direct.recording_id == RECORDING_ID
    assert direct.content_type == "events"

    with TestClient(app) as client:
        first = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/comparisons",
            json=_request("left-run", "right-run", _event_set_ref(reference_set)),
        )
        second = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/comparisons",
            json=_request("left-run", "right-run", _event_set_ref(reference_set)),
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == second.content
    body = first.json()
    assert body["mode"] == "paired_processor"
    assert body["left"]["revision_id"] is None
    assert body["left"]["event_set_ref"] == _event_set_ref(
        app.state.event_set_store.get(RECORDING_ID, "run-left-run", "1")
    )
    assert body["reference"]["revision_id"] is None
    assert body["reference"]["event_set_ref"] == _event_set_ref(reference_set)
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
        "ignored_frames": 0,
        "ignored_regions": 0,
        "ignored_pixels": 0,
        "neutralized_predictions": 0,
    }
    assert {item["outcome"] for item in body["items"]} == {"match", "extra", "not_reviewed"}

    invalid = _request("left-run", "right-run", _event_set_ref(reference_set))
    invalid["reference_event_set_ref"]["content_sha256"] = "0" * 64
    with TestClient(app) as client:
        assert (
            client.post(
                f"/api/recordings/{RECORDING_ID}/pipeline/comparisons", json=invalid
            ).status_code
            == 422
        )

    reopened = create_test_app(settings)
    with TestClient(reopened) as client:
        after_restart = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/comparisons",
            json=_request("left-run", "right-run", _event_set_ref(reference_set)),
        )
    assert after_restart.status_code == 200
    assert after_restart.content == first.content


def test_changed_upstream_input_has_no_paired_delta(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    runs = app.state.pipeline_run_store
    reference = _content(
        [
            {
                "event_id": "ref-1",
                "event_type": "card_state_changed",
                "start_us": 500_000,
                "end_us": 510_000,
            }
        ]
    )
    reference_set = _publish_revision(
        app, revision_id="reference-1", content=reference, origin="manual"
    )
    _create_complete_run(
        runs,
        app,
        run_id="left-run",
        revision_id="left-output",
        content=reference,
    )
    _create_complete_run(
        runs,
        app,
        run_id="right-run",
        revision_id="right-output",
        content=reference,
        extraction_policy={"policy_id": "event-extract/v2"},
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/comparisons",
            json=_request("left-run", "right-run", _event_set_ref(reference_set)),
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "upstream_experiment"
    assert response.json()["paired_delta"] is None


def test_partial_run_with_valid_output_is_comparable(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    runs = app.state.pipeline_run_store
    reference = _content(
        [
            {
                "event_id": "ref-1",
                "event_type": "card_state_changed",
                "start_us": 500_000,
                "end_us": 510_000,
            }
        ]
    )
    reference_set = _publish_revision(
        app, revision_id="reference-1", content=reference, origin="manual"
    )
    _create_partial_run(
        runs,
        app,
        run_id="partial-run",
        revision_id="partial-output",
        content=reference,
    )
    _create_complete_run(
        runs,
        app,
        run_id="complete-run",
        revision_id="complete-output",
        content=reference,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/comparisons",
            json=_request("partial-run", "complete-run", _event_set_ref(reference_set)),
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
            json=_request(
                "failed-run",
                "other-run",
                {"set_id": "reference-1", "version": "1", "content_sha256": "0" * 64},
            ),
        )

    assert response.status_code == 404 or response.status_code == 422
