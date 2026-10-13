from __future__ import annotations

import json
from pathlib import Path

import pytest

from doko_operations.reviewed_virtual_card_proposal_refresh import (
    build_0086_proposal_refresh_report,
    validate_0086_proposal_refresh_report,
)
from doko_operations.rfdetr_segmentation_campaign import sha256_json


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _fixture(root: Path) -> None:
    source = {
        "recording_id": "recording-1",
        "schema_version": "recording-video/v1",
        "relative_path": "data/intake/recordings/recording-1/video.mov",
        "byte_length": 10,
        "duration_us": 1_000_000,
        "video_sha256": "a" * 64,
    }
    inventory_core = {
        "schema_version": "reviewed-virtual-card-corpus-work-manifest/v1",
        "scope": {"candidate_recordings": ["recording-1"]},
        "recordings": [
            {
                "recording_id": "recording-1",
                "selected_event_revision_id": "reference-events-1",
                "event_frame_ids": ["frame-1", "frame-2"],
            }
        ],
    }
    _write_json(
        root / "docs/reports/0086-M0_Reviewed_Virtual_Card_Corpus_Inventory.json",
        {**inventory_core, "manifest_sha256": sha256_json(inventory_core)},
    )

    run_id = "card-scene-proposal-0086-91x59-recording-1"
    revision_id = f"card-scene-proposals-{run_id}-attempt-1"
    run_root = root / "data/operations/pipeline/runs" / run_id
    detector_content = {"schema_version": "visible-card-data/v1", "outcomes": []}
    detector_digest = sha256_json(detector_content)
    _write_json(
        root / "data/operations/pipeline/revisions/visible-cards-1/content.json",
        detector_content,
    )
    _write_json(
        root / "data/operations/pipeline/revisions/visible-cards-1/manifest.json",
        {
            "revision_id": "visible-cards-1",
            "recording_id": "recording-1",
            "content_type": "visible_cards",
            "content_schema": "visible-card-data/v1",
            "content_sha256": detector_digest,
            "source": source,
            "coverage": {
                "event_revision_id": "reference-events-1",
                "event_ids": ["frame-1", "frame-2"],
            },
            "producer": {"model_id": "local-rfdetr-segmentation.model-v1"},
        },
    )
    _write_json(
        run_root / "request.json",
        {
            "run_id": run_id,
            "processor_type": "visible-card-scene-proposal",
            "input_revision_ids": ["visible-cards-1"],
            "source": source,
        },
    )
    _write_json(
        run_root / "state.json",
        {
            "run_id": run_id,
            "status": "partial",
            "created_at": "2026-10-11T10:00:00Z",
            "completed_at": "2026-10-11T10:01:00Z",
            "item_ids": ["frame-1", "frame-2"],
            "output_revision_ids": [revision_id],
        },
    )
    frames = [
        {
            "frame_id": "frame-1",
            "status": "supported",
            "unsupported_reason": None,
            "proposal": {
                "fit_diagnostics": {
                    "diagnostics": {"recipe": {"recipe_version": "fixed-card-pose-grid-search/v5"}}
                }
            },
        },
        {
            "frame_id": "frame-2",
            "status": "unsupported",
            "unsupported_reason": "no pose could be initialized",
            "proposal": {
                "fit_diagnostics": {
                    "diagnostics": {"recipe": {"recipe_version": "fixed-card-pose-grid-search/v5"}}
                }
            },
        },
    ]
    content = {
        "schema_version": "proposed-card-scene-data/v1",
        "calibration": {"algorithm_version": "card-plane-geometry/v6"},
        "frames": frames,
    }
    _write_json(root / "data/operations/pipeline/revisions" / revision_id / "content.json", content)
    _write_json(
        root / "data/operations/pipeline/revisions" / revision_id / "manifest.json",
        {
            "revision_id": revision_id,
            "recording_id": "recording-1",
            "content_type": "card_scene_proposals",
            "content_schema": "proposed-card-scene-data/v1",
            "content_sha256": sha256_json(content),
            "source": source,
            "coverage": {
                "supported_frame_count": 1,
                "unsupported_frame_count": 1,
                "detector_revision_id": "visible-cards-1",
                "detector_revision_digest": detector_digest,
                "calibration_revision_id": "calibration-1",
                "calibration_digest": "c" * 64,
            },
        },
    )


def test_refresh_report_is_digest_backed_and_preserves_unsupported_frames(tmp_path: Path) -> None:
    _fixture(tmp_path)

    report = build_0086_proposal_refresh_report(tmp_path)
    validate_0086_proposal_refresh_report(report)

    assert report["summary"]["terminal_receipt_count"] == 1
    assert report["summary"]["status_counts"] == {"complete": 0, "partial": 1, "failed": 0}
    assert report["summary"]["event_frame_count_reconciles"] is True
    assert report["recordings"][0]["unsupported_frames"] == [
        {"frame_id": "frame-2", "reason": "no pose could be initialized"}
    ]


def test_refresh_report_rejects_frame_scope_drift(tmp_path: Path) -> None:
    _fixture(tmp_path)
    state_path = next((tmp_path / "data/operations/pipeline/runs").glob("*/state.json"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["item_ids"] = ["frame-1"]
    _write_json(state_path, state)

    with pytest.raises(ValueError, match="does not match frozen event scope"):
        build_0086_proposal_refresh_report(tmp_path)


def test_refresh_report_retains_failed_run_as_unresolved_event_scope(tmp_path: Path) -> None:
    _fixture(tmp_path)
    state_path = next((tmp_path / "data/operations/pipeline/runs").glob("*/state.json"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "status": "failed",
            "item_ids": [],
            "output_revision_ids": [],
            "terminal_failure": {"code": "inconsistent_card_geometry", "message": "unstable"},
        }
    )
    _write_json(state_path, state)

    report = build_0086_proposal_refresh_report(tmp_path)

    assert report["summary"]["unresolved_failure_recording_ids"] == ["recording-1"]
    assert report["summary"]["failed_run_frame_count"] == 2
    assert report["summary"]["event_frame_count_reconciles"] is True
    assert report["recordings"][0]["unresolved_event_frame_ids"] == ["frame-1", "frame-2"]
