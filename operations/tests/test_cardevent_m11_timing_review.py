import json
from pathlib import Path

from doko_operations.cardevent_m11 import publish_cardeventnet_m11_timing_review

REPOSITORY_ROOT = Path(__file__).parents[2]
CAMPAIGN_ID = "cardeventnet-0063-m9-hard-negative-ablation"
CAMPAIGN_DIR = REPOSITORY_ROOT / "data" / "model-campaigns" / CAMPAIGN_ID


def test_m11_reconciles_prose_recording_notes_and_replays_decoder_grid() -> None:
    result = publish_cardeventnet_m11_timing_review(
        CAMPAIGN_ID,
        repository_root=REPOSITORY_ROOT,
    )

    assert result["schema_version"] == "cardeventnet-m11-timing-reconciliation/v1"
    assert result["sealed_test_read"] is False
    assert result["system_holdout_read"] is False
    assert result["training_started"] is False
    assert result["decision_report"]["counts"] == {
        "items": 70,
        "no_event_confirmed": 18,
        "recordings": 6,
        "reference_confirmed": 25,
        "reference_corrected": 27,
        "regions": 47,
    }
    assert all(
        item["decision"]
        in {"reference_corrected", "reference_confirmed", "no_event_confirmed"}
        for item in result["decision_report"]["items"]
    )
    assert result["successor_dataset"]["revision_changed_recordings"] == [
        "cardeventnet-IMG_0090",
        "cardeventnet-IMG_0635",
        "cardeventnet-IMG_0644",
        "cardeventnet-IMG_0661",
    ]
    assert result["successor_dataset"]["preserved_partitions"]["test"] == [
        "cardeventnet-IMG_0669",
        "cardeventnet-IMG_0670",
        "cardeventnet-IMG_0671",
        "cardeventnet-IMG_0673",
        "cardeventnet-IMG_0674",
    ]
    assert result["decoder_grid"]["selection"]["selected_decoder"] is None
    assert [item["decoder_id"] for item in result["decoder_grid"]["candidates"]] == [
        "current_causal",
        "longer_peak_confirmation",
        "bounded_quiet_window",
    ]
    assert all(
        set(item)
        >= {
            "point_matches",
            "stable_end_matches",
            "detections_inside_intervals",
            "duplicate_detections_per_reviewed_change",
            "confirmed_no_event_triggers",
            "signed_timestamp_error_s",
            "causal_emission_delay_s",
        }
        for item in result["decoder_grid"]["candidates"]
    )


def test_m11_artifacts_are_reproducible_and_m10_operator_notes_survive() -> None:
    operator_path = CAMPAIGN_DIR / "m10-operator-review.json"
    before_operator = operator_path.read_bytes()
    paths = [
        CAMPAIGN_DIR / "m11-reference-decisions.json",
        CAMPAIGN_DIR / "m11-decoder-grid.json",
        CAMPAIGN_DIR / "m11-result.json",
        CAMPAIGN_DIR / "m11-report.md",
    ]
    before = tuple(path.read_bytes() for path in paths)

    publish_cardeventnet_m11_timing_review(
        CAMPAIGN_ID,
        repository_root=REPOSITORY_ROOT,
    )

    assert operator_path.read_bytes() == before_operator
    assert tuple(path.read_bytes() for path in paths) == before
    decisions = json.loads(paths[0].read_text(encoding="utf-8"))
    assert all(item["operator_notes"] for item in decisions["items"])
