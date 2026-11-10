"""Frozen recordings list contract and current growth baseline."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from doko_operations.pipeline_data import ProcessorRunRequest, RecordingVideoSource
from test_round_analysis_api import (
    RECORDING_ID as SERVICE_RECORDING_ID,
)
from test_round_analysis_api import (
    _analysis_payload,
    _backend,
    _upload_linked_package,
)

from dokodetector_backend.recordings_api import (
    RecordingAnalysisSummary,
    RecordingListResponse,
    RecordingPipelineStatusSummary,
    RecordingSummary,
)
from dokodetector_backend.round_analysis_contract import RoundAnalysisCreateRequest

RECORDING_ID = "catalog-growth-recording"
ANALYSIS_ID = UUID("550e8400-e29b-41d4-a716-446655440001")
PACKAGE_ID = UUID("550e8400-e29b-41d4-a716-446655440002")
STAGE_KEYS = (
    "events",
    "visible_cards",
    "visual_identities",
    "table_observations",
    "round_analyses",
)


def _recording(*, analyses: int, packages: int) -> RecordingSummary:
    now = datetime(2026, 11, 10, tzinfo=UTC)
    latest = RecordingAnalysisSummary(
        analysis_id=ANALYSIS_ID,
        recording_id=RECORDING_ID,
        round_id="round-growth",
        state="queued",
        total_evidence_packages=10,
        completed_evidence_packages=0,
        result_status=None,
        error=None,
        created_at=now,
        started_at=None,
        completed_at=None,
    )
    stages = [
        {"key": key, "state": "empty" if key != "events" else "active-run"} for key in STAGE_KEYS
    ]
    return RecordingSummary(
        recording_id=RECORDING_ID,
        source_asset_id="source-growth",
        video_id="video-growth",
        session_id="session-growth",
        state="accepted",
        source_sha256="0" * 64,
        received_at=now,
        round_id="round-growth",
        evidence_package_count=packages,
        analysis_count=analyses,
        latest_analysis=latest if analyses else None,
        pipeline_status=RecordingPipelineStatusSummary(
            schema_version="recording-pipeline-status/v1",
            stages=stages,
        ),
        can_start_analysis=False,
        analysis_blocker=(
            "No selected table observations or linked evidence packages are available."
        ),
    )


def test_recordings_list_keeps_order_status_and_blocker_contract() -> None:
    response = RecordingListResponse(recordings=[_recording(analyses=1, packages=1)])
    row = response.recordings[0]

    assert [stage.key for stage in row.pipeline_status.stages] == list(STAGE_KEYS)
    assert row.pipeline_status.stages[0].state == "active-run"
    assert row.can_start_analysis is False
    assert row.analysis_blocker is not None
    assert response.model_dump(mode="json")["recordings"][0]["recording_id"] == RECORDING_ID


def test_recordings_list_payload_stays_bounded_when_history_grows_tenfold() -> None:
    small = RecordingListResponse(recordings=[_recording(analyses=1, packages=1)])
    large = RecordingListResponse(recordings=[_recording(analyses=10, packages=10)])

    assert len(large.model_dump_json()) <= len(small.model_dump_json()) * 2


def _measure_real_catalog(
    root: Path, *, retained_items: int, head_proof: bool = False
) -> dict[str, object]:
    from dokodetector_backend import pipeline_workspace_service

    root.mkdir()
    client, app = _backend(root, synchronous=False)
    app.state.settings.recording_list_head_proof = head_proof
    target_packages = []
    with client:
        if head_proof:
            from test_recording_state_workflow import _snapshot_payload

            snapshot = _snapshot_payload()
            snapshot["recording_id"] = SERVICE_RECORDING_ID
            content = {key: value for key, value in snapshot.items() if key != "snapshot_id"}
            canonical = json.dumps(
                content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            snapshot["snapshot_id"] = "rs_" + hashlib.sha256(canonical.encode()).hexdigest()
            response = client.post(f"/api/recordings/{SERVICE_RECORDING_ID}/state", json=snapshot)
            assert response.status_code == 200, response.text
        for index in range(retained_items):
            package_id = f"550e8400-e29b-41d4-a716-{index + 1:012d}"
            target_packages.append(
                _upload_linked_package(
                    client,
                    package_id=package_id,
                    event_sequence=index + 1,
                )
            )

        stored_recording = app.state.recording_bundle_store.get_metadata(SERVICE_RECORDING_ID)
        assert stored_recording is not None
        source_mapping = RecordingVideoSource(
            recording_id=SERVICE_RECORDING_ID,
            relative_path=f"recordings/{SERVICE_RECORDING_ID}/videos/video-both.mov",
            video_sha256=stored_recording.source_sha256,
            byte_length=stored_recording.video_byte_length,
            duration_us=1_000_000,
        ).to_mapping()
        node_store = app.state.pipeline_lineage_writer.node_store

        def event_content(start_us: int) -> dict[str, object]:
            return {
                "schema_version": "event-data/v1",
                "events": [
                    {
                        "event_id": "catalog-event",
                        "event_type": "card_state_changed",
                        "start_us": start_us,
                        "end_us": start_us + 100,
                    }
                ],
            }

        revision_id = "catalog-target-r0"
        node_store.create(
            "catalog-target-events",
            "Catalog target events",
            "events",
            source_mapping,
            event_content(0),
            {},
            revision_id=revision_id,
        )
        for index in range(1, retained_items):
            next_revision_id = f"catalog-target-r{index}"
            node_store.save(
                "catalog-target-events",
                revision_id,
                event_content(index),
                {"fixture_revision": index},
                revision_id=next_revision_id,
            )
            revision_id = next_revision_id

        for index in range(retained_items):
            unrelated_source = dict(source_mapping, recording_id=f"unrelated-recording-{index}")
            node_store.create(
                f"catalog-unrelated-node-{index}",
                f"Unrelated node {index}",
                "events",
                unrelated_source,
                event_content(index),
                {},
            )

        run_store = app.state.pipeline_run_store
        target_request = {
            "schema_version": "processor-run-request/v1",
            "run_id": "catalog-target-active-run",
            "processor_type": "event-detection",
            "source": source_mapping,
            "input_revision_ids": [],
            "implementation": {"name": "catalog-fixture", "version": "v1"},
            "model": None,
            "configuration": {},
            "extraction_policy": {"policy_id": "catalog-fixture/v1"},
            "crop_policy": None,
        }
        run_store.create(ProcessorRunRequest.from_mapping(target_request))
        for index in range(retained_items):
            unrelated_run_source = dict(
                source_mapping,
                recording_id=f"unrelated-recording-{index}",
            )
            unrelated_request = dict(
                target_request,
                run_id=f"catalog-unrelated-run-{index}",
                source=unrelated_run_source,
            )
            run_store.create(ProcessorRunRequest.from_mapping(unrelated_request))
            run_store.start(unrelated_request["run_id"])
            run_store.fail(
                unrelated_request["run_id"],
                {"code": "fixture_failed", "message": "Retained terminal fixture."},
            )

        analysis_store = app.state.round_analysis_store
        newest_id = "550e8400-e29b-41d4-a716-000000000001"
        newest_request = RoundAnalysisCreateRequest.model_validate(
            _analysis_payload(analysis_id=newest_id, package_ids=[target_packages[0]])
        )
        analysis_store.create(
            newest_request,
            created_at=datetime(2030, 1, 1, tzinfo=UTC),
        )
        for index in range(retained_items - 1):
            analysis_id = f"550e8400-e29b-41d4-a716-{index + 100:012d}"
            request = RoundAnalysisCreateRequest.model_validate(
                _analysis_payload(analysis_id=analysis_id, package_ids=[target_packages[0]])
            )
            stored = analysis_store.create(
                request,
                created_at=datetime(2020, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
            ).analysis
            analysis_store.mark_failed(stored.analysis_id, "Retained terminal fixture.")
        for index in range(retained_items):
            unrelated_payload = _analysis_payload(
                analysis_id=f"550e8400-e29b-41d4-a716-{index + 200:012d}",
                package_ids=[target_packages[0]],
            )
            unrelated_payload["recording_id"] = f"unrelated-recording-{index}"
            unrelated_request = RoundAnalysisCreateRequest.model_validate(unrelated_payload)
            stored = analysis_store.create(
                unrelated_request,
                created_at=datetime(2021, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
            ).analysis
            analysis_store.mark_failed(stored.analysis_id, "Unrelated retained fixture.")

        counts: dict[str, int] = {
            "node_listed": 0,
            "node_manifest_reads": 0,
            "node_history_records": 0,
            "package_metadata_rows": 0,
            "analysis_rows_read": 0,
            "processor_run_directories": 0,
        }
        original_list_nodes = node_store.list_nodes
        original_get_node = node_store._get_unrecovered
        original_history = node_store.history
        original_package_list = app.state.evidence_package_store.list_metadata
        original_analysis_list = analysis_store.list
        original_enumerate = pipeline_workspace_service.enumerate_resource_directories

        def count_nodes(*args, **kwargs):
            nodes = original_list_nodes(*args, **kwargs)
            counts["node_listed"] += len(nodes)
            return nodes

        def count_history(*args, **kwargs):
            revisions = original_history(*args, **kwargs)
            counts["node_history_records"] += len(revisions)
            return revisions

        def count_node_manifest(*args, **kwargs):
            counts["node_manifest_reads"] += 1
            return original_get_node(*args, **kwargs)

        def count_packages(*args, **kwargs):
            packages = original_package_list(*args, **kwargs)
            counts["package_metadata_rows"] += len(packages)
            return packages

        def count_analyses(*args, **kwargs):
            analyses = original_analysis_list(*args, **kwargs)
            counts["analysis_rows_read"] += len(analyses)
            return analyses

        def count_directories(path, *args, **kwargs):
            result = original_enumerate(path, *args, **kwargs)
            if path == run_store.root:
                counts["processor_run_directories"] += len(result.paths)
            return result

        node_store.list_nodes = count_nodes
        node_store._get_unrecovered = count_node_manifest
        node_store.history = count_history
        app.state.evidence_package_store.list_metadata = count_packages
        analysis_store.list = count_analyses
        pipeline_workspace_service.enumerate_resource_directories = count_directories
        try:
            started = time.perf_counter()
            response = client.get("/v1/recordings")
            elapsed_ms = (time.perf_counter() - started) * 1000
        finally:
            node_store.list_nodes = original_list_nodes
            node_store._get_unrecovered = original_get_node
            node_store.history = original_history
            app.state.evidence_package_store.list_metadata = original_package_list
            analysis_store.list = original_analysis_list
            pipeline_workspace_service.enumerate_resource_directories = original_enumerate

    assert response.status_code == 200
    body = response.json()
    target = next(row for row in body["recordings"] if row["recording_id"] == SERVICE_RECORDING_ID)
    return {
        **counts,
        "recording_count": len(body["recordings"]),
        "response_bytes": len(response.content),
        "elapsed_ms": round(elapsed_ms, 3),
        "stage_states": [stage["state"] for stage in target["pipeline_status"]["stages"]],
        "latest_analysis_state": target["latest_analysis"]["state"],
        "active_runs": sum(
            run.status in {"queued", "running"}
            for run in app.state.pipeline_run_store.list_statuses()
            if run.recording_id == SERVICE_RECORDING_ID
        ),
        "returned_package_ids": target["evidence_package_count"],
        "returned_analysis_rows": target["analysis_count"],
    }


def test_head_proof_measures_each_history_source(tmp_path: Path) -> None:
    small = _measure_real_catalog(tmp_path / "small", retained_items=1, head_proof=True)
    large = _measure_real_catalog(tmp_path / "large", retained_items=10, head_proof=True)
    print(f"HEAD proof growth: 1x={small}, 10x={large}")
    assert small["node_listed"] == large["node_listed"] == 0
    assert small["node_manifest_reads"] == large["node_manifest_reads"] == 0
    assert small["node_history_records"] == large["node_history_records"] == 0
    for counter in ("package_metadata_rows", "analysis_rows_read", "processor_run_directories"):
        assert large[counter] > small[counter]


@pytest.fixture(scope="module")
def real_catalog_growth(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, object], dict[str, object]]:
    tmp_path = tmp_path_factory.mktemp("real-recording-catalog-growth")
    return (
        _measure_real_catalog(tmp_path / "small", retained_items=1),
        _measure_real_catalog(tmp_path / "large", retained_items=10),
    )


def test_real_recordings_route_keeps_current_state_fixed_under_history_growth(
    real_catalog_growth: tuple[dict[str, object], dict[str, object]],
) -> None:
    small, large = real_catalog_growth
    assert large["recording_count"] == small["recording_count"] == 1
    assert large["stage_states"] == small["stage_states"]
    assert large["latest_analysis_state"] == small["latest_analysis_state"] == "queued"
    assert large["active_runs"] == small["active_runs"] == 1


def test_real_recordings_route_exposes_growth_in_each_source_family(
    real_catalog_growth: tuple[dict[str, object], dict[str, object]],
) -> None:
    small, large = real_catalog_growth
    for counter in (
        "node_listed",
        "node_history_records",
        "package_metadata_rows",
        "analysis_rows_read",
        "processor_run_directories",
    ):
        assert large[counter] > small[counter], f"{counter}: small={small}, large={large}"


def test_real_recordings_route_payload_stays_bounded_as_history_grows_tenfold(
    real_catalog_growth: tuple[dict[str, object], dict[str, object]],
) -> None:
    small, large = real_catalog_growth
    assert large["response_bytes"] <= small["response_bytes"] * 2, (
        f"response_bytes grew beyond the bound: small={small}, large={large}"
    )


@pytest.mark.xfail(
    strict=True,
    reason="M0 baseline: real catalog readers enumerate retained and unrelated source rows.",
)
@pytest.mark.parametrize(
    "counter",
    [
        "node_listed",
        "node_history_records",
        "package_metadata_rows",
        "analysis_rows_read",
        "processor_run_directories",
    ],
)
def test_real_recordings_route_reads_stay_bounded_as_retained_data_grows_tenfold(
    real_catalog_growth: tuple[dict[str, object], dict[str, object]],
    counter: str,
) -> None:
    small, large = real_catalog_growth
    assert large[counter] <= small[counter] * 2, (
        f"{counter} grew beyond the bound: small={small}, large={large}"
    )
