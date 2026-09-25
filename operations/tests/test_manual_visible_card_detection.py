from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from doko_operations.manual_visible_card_detection import (
    render_manual_visible_card_detection,
    run_manual_visible_card_detection,
)


def test_visible_card_batch_freezes_event_revision_and_records_run_lineage() -> None:
    readiness = {
        "ready": True,
        "errors": [],
        "recordings": [
            {"recording_id": "rec-1", "event_revision_id": "events-r7", "errors": []}
        ],
    }
    calls: list[tuple[str, str, Mapping[str, Any] | None]] = []

    def request_json(
        path: str, *, method: str, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        calls.append((path, method, payload))
        if method == "POST":
            request = payload["request"]
            assert request["event_revision_id"] == "events-r7"
            assert request["configuration"]["provider"] == "local-rfdetr-segmentation"
            return {"run_id": "run-1", "status": "queued"}
        if path.endswith("/result"):
            return {
                "revisions": [{"manifest": {"revision_id": "visible-r8"}}]
            }
        return {
            "run_id": "run-1",
            "status": "complete",
            "request": {
                "input_revision_ids": ["events-r7"],
                "model": {"name": "rfdetr", "version": "bundle-42"},
                "implementation": {"name": "visible-card-detector-adapter", "version": "v1"},
                "configuration": {"provider": "local-rfdetr-segmentation"},
            },
            "state": {"output_revision_ids": ["visible-r8"]},
        }

    report = run_manual_visible_card_detection(
        ["rec-1"],
        preflight=lambda: readiness,
        request_json=request_json,
        sleep=lambda _seconds: None,
        monotonic=iter([0.0, 0.0, 0.1]).__next__,
        new_run_id=lambda: "run-1",
    )

    recording = report["recordings"][0]
    assert recording["status"] == "complete"
    assert recording["input_revision_ids"] == ["events-r7"]
    assert recording["output_revision_ids"] == ["visible-r8"]
    assert recording["model"] == {"name": "rfdetr", "version": "bundle-42"}
    assert [method for _path, method, _payload in calls] == ["POST", "GET", "GET"]
    assert "visible-r8" in render_manual_visible_card_detection(report)


def test_blocked_preflight_starts_no_runs() -> None:
    calls: list[str] = []
    report = run_manual_visible_card_detection(
        ["rec-1"],
        preflight=lambda: {"ready": False, "errors": ["provider unavailable"], "recordings": []},
        request_json=lambda path, **_kwargs: calls.append(path) or {},
    )

    assert report["ready"] is False
    assert report["errors"] == ["provider unavailable"]
    assert calls == []


def test_failed_recording_does_not_hide_later_recording() -> None:
    readiness = {
        "ready": True,
        "errors": [],
        "recordings": [
            {"recording_id": "rec-1", "event_revision_id": "events-r1"},
            {"recording_id": "rec-2", "event_revision_id": "events-r2"},
        ],
    }

    def request_json(
        path: str, *, method: str, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        if method == "POST" and "rec-1" in path:
            raise OSError("backend rejected the first run")
        if method == "POST":
            return {"run_id": payload["request"]["run_id"], "status": "failed"}
        return {}

    reports = iter(("run-1", "run-2"))
    report = run_manual_visible_card_detection(
        ["rec-1", "rec-2"],
        preflight=lambda: readiness,
        request_json=request_json,
        new_run_id=lambda: next(reports),
    )

    assert [item["recording_id"] for item in report["recordings"]] == ["rec-1", "rec-2"]
    assert report["recordings"][0]["status"] == "unavailable"
    assert report["recordings"][1]["status"] == "failed"


def test_result_fetch_error_does_not_change_terminal_processor_status() -> None:
    readiness = {
        "ready": True,
        "errors": [],
        "recordings": [
            {"recording_id": "rec-1", "event_revision_id": "events-r1"}
        ],
    }

    def request_json(path: str, *, method: str, **_kwargs: Any) -> dict[str, Any]:
        if method == "POST":
            return {"run_id": "run-1", "status": "complete"}
        if path.endswith("/result"):
            raise OSError("result endpoint unavailable")
        raise AssertionError(f"unexpected request: {path}")

    report = run_manual_visible_card_detection(
        ["rec-1"],
        preflight=lambda: readiness,
        request_json=request_json,
        new_run_id=lambda: "run-1",
    )

    assert report["recordings"][0]["status"] == "complete"
    assert report["recordings"][0]["error"] == "result endpoint unavailable"
