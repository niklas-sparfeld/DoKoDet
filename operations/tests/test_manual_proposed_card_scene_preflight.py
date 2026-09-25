from __future__ import annotations

from pathlib import Path

import pytest

from doko_operations import cli
from doko_operations.manual_proposed_card_scene_preflight import (
    ManualProposedCardScenePreflightError,
    preflight_manual_proposed_card_scene_runs,
    read_recording_ids,
)


def test_recording_list_ignores_blank_lines_and_rejects_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "recordings.txt"
    path.write_text("recording-1\n\n recording-2 \n", encoding="utf-8")

    assert read_recording_ids(path) == ["recording-1", "recording-2"]

    path.write_text("recording-1\nrecording-1\n", encoding="utf-8")
    with pytest.raises(ManualProposedCardScenePreflightError, match="duplicate recording ID"):
        read_recording_ids(path)


def test_preflight_checks_provider_and_all_recordings_without_starting_runs() -> None:
    responses = {
        "/health/ready": {"status": "ok"},
        "/api/processors/visible-cards/local-rfdetr-segmentation/availability": {
            "provider": "local-rfdetr-segmentation",
            "available": True,
            "bundle_identity": {"bundle_digest": "abc123"},
        },
        "/v1/recordings": {
            "recordings": [{"recording_id": "recording-1"}, {"recording_id": "recording-2"}]
        },
        "/api/recordings/recording-1/pipeline/events/selection": {
            "selection": {
                "selected_generated_revision_id": "events-1",
                "selected_completed_reference_revision_id": None,
            }
        },
        "/api/recordings/recording-2/pipeline/events/selection": {"selection": None},
    }
    requested: list[str] = []

    def get(path: str) -> dict:
        requested.append(path)
        return responses[path]

    report = preflight_manual_proposed_card_scene_runs(
        ["recording-1", "recording-2"], get_json=get
    )

    assert not report["ready"]
    assert report["recordings"][0]["event_revision_id"] == "events-1"
    assert report["recordings"][1]["errors"] == ["no selected event revision is available"]
    assert all("/runs" not in path for path in requested)
    assert "/api/recordings/recording-2/pipeline/events/selection" in requested


def test_preflight_reports_an_unavailable_provider_before_any_run() -> None:
    responses = {
        "/health/ready": {"status": "ok"},
        "/api/processors/visible-cards/local-rfdetr-segmentation/availability": {
            "available": False,
            "error": "bundle is missing",
        },
        "/v1/recordings": {"recordings": [{"recording_id": "recording-1"}]},
        "/api/recordings/recording-1/pipeline/events/selection": {
            "selection": {"selected_generated_revision_id": "events-1"}
        },
    }
    report = preflight_manual_proposed_card_scene_runs(
        ["recording-1"], get_json=lambda path: responses[path]
    )

    assert not report["ready"]
    assert any("bundle is missing" in error for error in report["errors"])


def test_cli_emits_json_and_returns_success_for_a_ready_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "recordings.txt"
    path.write_text("recording-1\n", encoding="utf-8")
    responses = {
        "/health/ready": {"status": "ok"},
        "/api/processors/visible-cards/local-rfdetr-segmentation/availability": {
            "provider": "local-rfdetr-segmentation",
            "available": True,
            "bundle_identity": {"bundle_digest": "abc123"},
        },
        "/v1/recordings": {"recordings": [{"recording_id": "recording-1"}]},
        "/api/recordings/recording-1/pipeline/events/selection": {
            "selection": {"selected_generated_revision_id": "events-1"}
        },
    }
    monkeypatch.setattr(
        "doko_operations.manual_proposed_card_scene_preflight._get_json",
        lambda _url, endpoint, _timeout: responses[endpoint],
    )

    status = cli.main(
        [
            "pipeline",
            "proposed-card-scenes-preflight",
            "--recordings",
            str(path),
            "--format",
            "json",
        ]
    )

    assert status == 0
    assert '"ready": true' in capsys.readouterr().out
