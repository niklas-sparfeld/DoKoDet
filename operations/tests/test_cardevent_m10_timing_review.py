from __future__ import annotations

import json
from pathlib import Path

from doko_operations.cardevent_m10 import publish_cardeventnet_m10_timing_review

REPOSITORY_ROOT = Path(__file__).parents[2]
CAMPAIGN_ID = "cardeventnet-0063-m9-hard-negative-ablation"
CAMPAIGN_DIR = REPOSITORY_ROOT / "data" / "model-campaigns" / CAMPAIGN_ID


def test_m10_publishes_the_six_recording_timing_review_packet() -> None:
    packet = publish_cardeventnet_m10_timing_review(
        CAMPAIGN_ID,
        repository_root=REPOSITORY_ROOT,
    )

    assert packet["schema_version"] == "cardeventnet-m10-timing-review/v1"
    assert packet["selection"]["partition"] == "validation"
    assert packet["selection"]["threshold"] == 0.4271905720233917
    assert packet["selection"]["decoder"] == {
        "min_event_gap_s": 0.625,
        "peak_confirmation_s": 0.125,
    }
    assert packet["counts"] == {
        "confirmed_false_triggers": 20,
        "in_progress_detections": 22,
        "missed_events": 28,
        "raw_items": 70,
        "regions": 47,
    }
    assert [item["recording_id"] for item in packet["operator_checklist"]] == [
        "cardeventnet-IMG_0090",
        "cardeventnet-IMG_0644",
        "cardeventnet-IMG_0635",
        "cardeventnet-IMG_0652",
        "cardeventnet-IMG_0091",
        "cardeventnet-IMG_0661",
    ]
    assert any(
        region["recording_id"] == "cardeventnet-IMG_0090"
        and region["focus_range_s"] == [61.0, 64.875]
        and len(region["item_ids"]) == 4
        for region in packet["regions"]
    )
    assert any(
        region["recording_id"] == "cardeventnet-IMG_0644"
        and region["focus_range_s"] == [16.625, 21.25]
        and len(region["item_ids"]) == 5
        for region in packet["regions"]
    )
    assert all(item["source_frame_evidence"] for item in packet["items"])
    assert all(item["reference_revision"]["event_revision_id"] for item in packet["items"])
    assert packet["sealed_test_read"] is False
    assert packet["system_holdout_read"] is False

    packet_path = REPOSITORY_ROOT / packet["packet_path"]
    completion_path = REPOSITORY_ROOT / packet["operator_completion_artifact"]
    report_path = REPOSITORY_ROOT / packet["report_path"]
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")
    assert (
        json.loads(packet_path.read_text(encoding="utf-8"))["packet_digest"]
        == packet["packet_digest"]
    )
    assert completion["status"] == "pending_operator_review"
    assert completion["packet"]["sha256"] == packet["packet_digest"]
    assert "mise exec -- uv run --project backend dokodetector-backend" in report
    assert "cd web" in report
    assert "mise exec -- npm run dev" in report
    assert "21.021–23.021" in report
    assert "89.250" in report
    assert "m10-operator-review.json" in report


def test_m10_output_is_reproducible() -> None:
    packet_path = CAMPAIGN_DIR / "m10-timing-review.json"
    completion_path = CAMPAIGN_DIR / "m10-operator-review.json"
    report_path = CAMPAIGN_DIR / "m10-report.md"
    before = tuple(path.read_bytes() for path in (packet_path, completion_path, report_path))

    packet = publish_cardeventnet_m10_timing_review(
        CAMPAIGN_ID,
        repository_root=REPOSITORY_ROOT,
    )

    after = tuple(path.read_bytes() for path in (packet_path, completion_path, report_path))
    assert before == after
    assert (
        packet["packet_digest"]
        == "eb47261ca4236c59c9dbab4565c77a4f8cec66804b9413e8c956a54f8444bc12"
    )
