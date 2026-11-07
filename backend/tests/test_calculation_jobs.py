from __future__ import annotations

import time
from pathlib import Path

import pytest
from app_factory import create_test_app
from doko_operations.card_plane_geometry import TablePlaneCalibration
from fastapi.testclient import TestClient
from table_evidence_analyzer.card_scene_contract import CalibrationDraft

from dokodetector_backend.config import Settings


def _preview_fixture(tmp_path: Path):
    app = create_test_app(Settings(_env_file=None, evidence_root=tmp_path / "runtime"))
    participant = app.state.calculation_jobs
    calibration = TablePlaneCalibration.create(
        calibration_revision_id="calibration-1",
        recording_id="recording-1",
        source_revision="detector-1",
        frame_width=100,
        frame_height=100,
        image_to_table=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        table_to_image=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        card_short_size=1,
        card_long_size=91 / 59,
        candidate_receipt_digests=[],
        diagnostics={},
    )
    draft = CalibrationDraft.create(
        draft_id="draft-1",
        recording_id="recording-1",
        detector_revision_id="detector-1",
        detector_revision_digest="a" * 64,
        base_calibration_revision_id="calibration-1",
        base_calibration_digest=calibration.calibration_digest,
        source_frame_digests={},
        anchors=[],
        commands=[],
    )
    snapshot = {
        "proposal_revision_id": "proposal-1",
        "proposal_digest": "b" * 64,
        "draft": draft.to_mapping(),
        "calibration": calibration.to_mapping(),
        "frame_scenes": [],
    }
    participant._snapshot = lambda _recording, _body: snapshot
    return app, snapshot


def test_preview_is_snapshot_bound_and_rejects_changed_evidence(tmp_path: Path) -> None:
    app, snapshot = _preview_fixture(tmp_path)
    participant = app.state.calculation_jobs
    job = app.state.job_manager_service.run_inline(
        "550e8400-e29b-41d4-a716-446655440090",
        {
            "type": "calibration_preview",
            "context": {"recording_id": "recording-1"},
            "request": {"draft_id": "draft-1", "proposal_revision_id": "proposal-1"},
        },
    )
    assert job.state == "succeeded", job.failure
    assert participant.current_preview(job)["preview_complete"] is True
    snapshot["frame_scenes"] = [{"frame_id": "changed"}]
    with pytest.raises(ValueError, match="stale"):
        participant.current_preview(job)
    assert participant.verify_publication(job, job.results)


def test_preview_job_http_and_stale_result(tmp_path: Path) -> None:
    app, snapshot = _preview_fixture(tmp_path)
    with TestClient(app) as client:
        accepted = client.post(
            "/api/jobs",
            headers={"Idempotency-Key": "550e8400-e29b-41d4-a716-446655440090"},
            json={
                "type": "calibration_preview",
                "context": {"recording_id": "recording-1"},
                "request": {"draft_id": "draft-1", "proposal_revision_id": "proposal-1"},
            },
        )
        assert accepted.status_code == 202, accepted.text
        job_id = accepted.json()["id"]
        deadline = time.monotonic() + 5
        while True:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["state"] not in {"queued", "running"}:
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert job["state"] == "succeeded", job
        assert client.get(f"/api/jobs/{job_id}/calibration-preview").status_code == 200
        snapshot["frame_scenes"] = [{"frame_id": "new-evidence"}]
        assert client.get(f"/api/jobs/{job_id}/calibration-preview").status_code == 409


def test_cancelled_preview_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dokodetector_backend import calculation_jobs
    from dokodetector_backend.job_models import CancellationToken, JobCancelled
    from dokodetector_backend.job_store import JobManager

    app, _ = _preview_fixture(tmp_path)
    registry = app.state.job_type_registry
    token = CancellationToken()
    original = calculation_jobs.build_calibration_preview

    def cancel_after_calculation(*args, **kwargs):
        result = original(*args, **kwargs)
        token.request()
        return result

    monkeypatch.setattr(calculation_jobs, "build_calibration_preview", cancel_after_calculation)
    with JobManager(
        app.state.job_manager_service.operations_root,
        registry,
        verify_publication=registry.verify_publication,
    ) as manager:
        job = manager.accept(
            "550e8400-e29b-41d4-a716-446655440090",
            {
                "type": "calibration_preview",
                "context": {"recording_id": "recording-1"},
                "request": {"draft_id": "draft-1", "proposal_revision_id": "proposal-1"},
            },
        )
        manager.transition(job.id, "running")
        with pytest.raises(JobCancelled):
            app.state.calculation_jobs.handle(job, registry.claims_for(job), token, manager)
        assert not (app.state.calculation_jobs.root / job.id / "result.json").exists()


def test_snapshot_reads_proposal_calibration_mapping(tmp_path: Path) -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock

    from dokodetector_backend.calculation_jobs import CalculationJobs

    draft = SimpleNamespace(to_mapping=lambda: {"draft_id": "draft-1"})
    calibration = {"calibration_digest": "a" * 64}
    proposal_node = object()
    proposal_revision = SimpleNamespace(content_sha256="b" * 64)
    data = SimpleNamespace(calibration=calibration)
    frame_scenes = Mock(return_value=())
    service = SimpleNamespace(
        store=SimpleNamespace(load=Mock(return_value=draft)),
        _proposal=Mock(
            return_value=(
                (proposal_node, proposal_revision),
                object(),
                data,
            )
        ),
        _require_current_source=Mock(),
        _frame_scenes=frame_scenes,
    )
    participant = CalculationJobs(tmp_path, service, None)
    snapshot = participant._snapshot(
        "recording-1", {"draft_id": "draft-1", "proposal_revision_id": "proposal-1"}
    )
    assert snapshot["calibration"] == calibration
    assert snapshot["proposal_digest"] == "b" * 64
    frame_scenes.assert_called_once_with("recording-1", "proposal-1", data)
