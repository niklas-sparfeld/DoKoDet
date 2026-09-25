from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from doko_operations.manual_proposed_card_scene_generation import (
    render_manual_proposed_card_scene_generation,
    run_manual_proposed_card_scene_generation,
)


def test_proposal_batch_pins_selected_rf_detr_revision_and_reports_calibration() -> None:
    calls: list[tuple[str, str, Mapping[str, Any] | None]] = []

    def request_json(
        path: str, *, method: str, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        calls.append((path, method, payload))
        if path.endswith("/selection"):
            return {
                "selection": {"selected_generated_revision_id": "visible-r1"}
            }
        if path.endswith("/runs"):
            return {
                "runs": [
                    {
                        "status": "complete",
                        "request": {"model": {"name": "local-rfdetr-segmentation"}},
                        "state": {"output_revision_ids": ["visible-r1"]},
                    }
                ]
            }
        if method == "POST":
            assert payload == {
                "run_id": "proposal-1",
                "visible_card_revision_id": "visible-r1",
            }
            return {"run_id": "proposal-1", "status": "queued"}
        if path.endswith("/result"):
            return {
                "revisions": [
                    {
                        "manifest": {
                            "revision_id": "scenes-r1",
                            "coverage": {
                                "calibration_revision_id": "calibration-r1",
                                "supported_frame_count": 7,
                                "unsupported_frame_count": 2,
                            },
                        }
                    }
                ]
            }
        return {
            "run_id": "proposal-1",
            "status": "complete",
            "state": {"output_revision_ids": ["scenes-r1"]},
        }

    report = run_manual_proposed_card_scene_generation(
        ["rec-1"],
        request_json=request_json,
        new_run_id=lambda: "proposal-1",
        sleep=lambda _seconds: None,
        monotonic=iter([0.0, 0.0, 0.1]).__next__,
    )

    item = report["recordings"][0]
    assert report["ready"] is True
    assert item["status"] == "complete"
    assert item["visible_card_revision_id"] == "visible-r1"
    assert item["output_revision_ids"] == ["scenes-r1"]
    assert item["calibration_revision_id"] == "calibration-r1"
    assert item["supported_frame_count"] == 7
    assert item["unsupported_frame_count"] == 2
    assert [method for _path, method, _payload in calls] == ["GET", "GET", "POST", "GET", "GET"]
    assert "scenes-r1" in render_manual_proposed_card_scene_generation(report)


def test_invalid_selection_blocks_all_proposal_runs() -> None:
    calls: list[tuple[str, str]] = []

    def request_json(path: str, *, method: str, **_kwargs: Any) -> dict[str, Any]:
        calls.append((path, method))
        if path.endswith("/selection"):
            return {"selection": None}
        raise AssertionError("a blocked preflight must not inspect or start runs")

    report = run_manual_proposed_card_scene_generation(
        ["rec-1", "rec-2"], request_json=request_json
    )

    assert report["ready"] is False
    assert report["recordings"] == []
    assert len(report["errors"]) == 2
    assert calls == [
        ("/api/recordings/rec-1/pipeline/visible-cards/selection", "GET"),
        ("/api/recordings/rec-2/pipeline/visible-cards/selection", "GET"),
    ]


def test_preflight_rejects_non_rf_detr_revision_before_any_run() -> None:
    calls: list[tuple[str, str]] = []

    def request_json(path: str, *, method: str, **_kwargs: Any) -> dict[str, Any]:
        calls.append((path, method))
        if path.endswith("/selection"):
            return {"selection": {"selected_generated_revision_id": "visible-r1"}}
        return {
            "runs": [
                {
                    "status": "complete",
                    "request": {"model": {"name": "other-detector"}},
                    "state": {"output_revision_ids": ["visible-r1"]},
                }
            ]
        }

    report = run_manual_proposed_card_scene_generation(
        ["rec-1"], request_json=request_json
    )

    assert report["ready"] is False
    assert report["recordings"] == []
    assert "not a completed local RF-DETR result" in report["errors"][0]
    assert [method for _path, method in calls] == ["GET", "GET"]


def test_failed_proposal_does_not_hide_later_recording() -> None:
    def request_json(
        path: str, *, method: str, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        if path.endswith("/selection"):
            recording_id = path.split("/")[3]
            return {"selection": {"selected_generated_revision_id": f"visible-{recording_id}"}}
        if path.endswith("/runs"):
            recording_id = path.split("/")[3]
            return {
                "runs": [
                    {
                        "status": "complete",
                        "request": {"model": {"name": "local-rfdetr-segmentation"}},
                        "state": {"output_revision_ids": [f"visible-{recording_id}"]},
                    }
                ]
            }
        if method == "POST" and "rec-1" in path:
            return {
                "run_id": payload["run_id"],
                "status": "failed",
                "state": {"terminal_failure": {"message": "no calibration"}},
            }
        if method == "POST":
            return {
                "run_id": payload["run_id"],
                "status": "complete",
                "state": {"output_revision_ids": ["scene-2"]},
            }
        if path.endswith("/result"):
            return {
                "revisions": [
                    {"manifest": {"revision_id": "scene-2", "coverage": {}}}
                ]
            }
        raise AssertionError(f"unexpected request: {method} {path}")

    ids = iter(("proposal-1", "proposal-2"))
    report = run_manual_proposed_card_scene_generation(
        ["rec-1", "rec-2"], request_json=request_json, new_run_id=lambda: next(ids)
    )

    assert [item["status"] for item in report["recordings"]] == ["failed", "complete"]
    assert report["recordings"][1]["output_revision_ids"] == ["scene-2"]
