from __future__ import annotations

import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from fastapi.testclient import TestClient

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from app_factory import create_test_app  # noqa: E402
from run_interactive_ui_read_performance import (  # noqa: E402
    _seed_jobs,
    read_scenarios,
)

from dokodetector_backend.config import Settings  # noqa: E402
from dokodetector_backend.job_store import FakeParticipant, JobManager  # noqa: E402


def test_read_scenarios_cover_every_inventoried_ui_json_get() -> None:
    scenarios = read_scenarios()
    names = [case["name"] for case in scenarios]
    assert len(names) == len(set(names))
    assert all(
        case["status"] >= 200 and case["path"].startswith(("/api/", "/v1/")) for case in scenarios
    )
    assert {case["route"] for case in scenarios} >= {
        "/api/jobs",
        "/api/recordings/{recording_id}/pipeline",
        "/v1/recordings",
        "/v1/round-analyses/{analysis_id}/timeline",
    }
    assert {case["name"] for case in scenarios} >= {
        "pipeline_workspace_full",
        "pipeline_workspace_stage_query",
        "node_revision_max_visual_identity",
        "node_revision_max_visible_card",
        "frame_review_queue_unavailable",
        "jobs_history_page",
        "job_detail",
        "job_detail_missing",
        "job_calibration_preview_wrong_type",
        "job_logs_first_page",
        "job_logs_missing",
    }


def test_seeded_job_history_uses_production_intent_and_job_readers(tmp_path: Path) -> None:
    target_job_id = _seed_jobs(tmp_path, 12)
    with JobManager(
        tmp_path / "data/operations", FakeParticipant(tmp_path / "fake-runs")
    ) as manager:
        jobs = manager.list_jobs()
        assert len(jobs) == 12
        assert manager.get(target_job_id).context["recording_id"] == "cardeventnet-IMG_0650"
        assert sum(job.context["recording_id"] == "cardeventnet-IMG_0650" for job in jobs) == 6
        assert manager.logs(target_job_id, after=0, limit=10) == {
            "entries": [],
            "next_after": 0,
            "truncated_before": 0,
        }


def test_job_history_filter_and_cursor_preserve_pages_as_unrelated_history_grows(
    tmp_path: Path,
) -> None:
    expected_ids = [
        str(uuid5(NAMESPACE_URL, f"doko-ui-perf-m3-target-{index}")) for index in reversed(range(6))
    ]
    page_results = []
    for history_size in (12, 300):
        root = tmp_path / str(history_size)
        root.mkdir()
        _seed_jobs(root, history_size)
        settings = Settings(
            _env_file=None,
            repository_root=Path(__file__).resolve().parents[2],
            evidence_root=root / "runtime",
            operations_root=root / "data/operations",
            frontend_dist=root / "frontend",
            repository_intake_root=root / "recordings",
            evidence_package_intake_root=root / "packages",
            pending_video_root=root / "pending",
        )
        app = create_test_app(settings)
        with TestClient(app) as client:
            first = client.get(
                "/api/jobs",
                params={
                    "scope": "history",
                    "recording_id": "cardeventnet-IMG_0650",
                    "limit": 3,
                },
            )
            assert first.status_code == 200
            first_json = first.json()
            first_ids = [item["id"] for item in first_json["items"]]
            cursor = first_json["next_cursor"]
            assert cursor
            second = client.get(
                "/api/jobs",
                params={
                    "scope": "history",
                    "recording_id": "cardeventnet-IMG_0650",
                    "limit": 3,
                    "cursor": cursor,
                },
            )
            assert second.status_code == 200
            second_json = second.json()
            second_ids = [item["id"] for item in second_json["items"]]
            assert second_json["next_cursor"] is None
            assert len(first_ids) == len(second_ids) == 3
            assert first_ids + second_ids == expected_ids
            assert not set(first_ids) & set(second_ids)
            page_results.append(first_ids + second_ids)
    assert page_results[0] == page_results[1]


def test_job_detail_logs_and_calibration_preview_error_reads(tmp_path: Path) -> None:
    target_job_id = _seed_jobs(tmp_path, 12)
    settings = Settings(
        _env_file=None,
        repository_root=Path(__file__).resolve().parents[2],
        evidence_root=tmp_path / "runtime",
        operations_root=tmp_path / "data/operations",
        frontend_dist=tmp_path / "frontend",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "packages",
        pending_video_root=tmp_path / "pending",
    )
    app = create_test_app(settings)
    with TestClient(app) as client:
        detail = client.get(f"/api/jobs/{target_job_id}")
        assert detail.status_code == 200
        assert detail.json()["id"] == target_job_id
        assert detail.json()["state"] == "failed"

        missing_detail = client.get("/api/jobs/22222222-2222-5222-8222-222222222222")
        assert missing_detail.status_code == 404
        assert missing_detail.json()["error"]["code"] == "job_not_found"

        wrong_type = client.get(f"/api/jobs/{target_job_id}/calibration-preview")
        assert wrong_type.status_code == 409
        assert wrong_type.json()["error"]["code"] == "calibration_preview_unavailable"

        missing_logs = client.get("/api/jobs/22222222-2222-5222-8222-222222222222/logs")
        assert missing_logs.status_code == 404
        assert missing_logs.json()["error"]["code"] == "job_not_found"
