from __future__ import annotations

import json
from pathlib import Path

from doko_operations.cardevent_m14 import (
    M14_CAMPAIGN_ID,
    prepare_cardeventnet_m14_integration_handoff,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
SOURCE_CAMPAIGN_ID = "cardeventnet-0063-m9-hard-negative-ablation"
CAMPAIGN_DIR = REPOSITORY_ROOT / "data" / "model-campaigns" / M14_CAMPAIGN_ID


def test_m14_locks_the_m9_development_baseline_without_running_operator_commands() -> None:
    result = prepare_cardeventnet_m14_integration_handoff(
        SOURCE_CAMPAIGN_ID,
        repository_root=REPOSITORY_ROOT,
    )
    lock = json.loads((CAMPAIGN_DIR / "integration-lock.json").read_text(encoding="utf-8"))
    sealed = json.loads((CAMPAIGN_DIR / "sealed-test-handoff.json").read_text(encoding="utf-8"))
    export = json.loads((CAMPAIGN_DIR / "export-parity-handoff.json").read_text(encoding="utf-8"))

    assert result["state"] == "ready_for_operator"
    assert lock["candidate_id"] == "m9_hard_negative_v1"
    assert lock["threshold"]["value"] == 0.4271905720233917
    assert lock["decoder"]["peak_confirmation_s"] == 0.125
    assert lock["decoder"]["min_event_gap_s"] == 0.625
    assert lock["production_promotion_eligible"] is False
    assert lock["decision"]["failed_gate_names"] == [
        "stable_end_matches",
        "confirmed_no_event_triggers",
        "event_presence_recall",
    ]
    assert len(lock["successor_validation_lineage"]["reference_revisions"]) == 76
    assert sealed["one_time_policy"]["maximum_evaluations"] == 1
    assert sealed["one_time_policy"]["tuning_allowed"] is False
    assert "--partition test" in sealed["command"]
    assert "--threshold 0.4271905720233917" in sealed["command"]
    assert export["parity"]["required"] is True
    assert export["parity"]["skip_parity_allowed"] is False
    assert "--skip-parity" not in export["command"]
    assert result["long_commands_started"] is False
    assert result["sealed_test_read"] is False
    assert result["current_champion_changed"] is False
    assert result["promotion_receipt_written"] is False


def test_m14_artifacts_are_reproducible() -> None:
    paths = (
        CAMPAIGN_DIR / "integration-lock.json",
        CAMPAIGN_DIR / "sealed-test-handoff.json",
        CAMPAIGN_DIR / "export-parity-handoff.json",
        CAMPAIGN_DIR / "m14-result.json",
        CAMPAIGN_DIR / "m14-report.md",
    )
    before = {path: path.read_bytes() for path in paths}

    prepare_cardeventnet_m14_integration_handoff(
        SOURCE_CAMPAIGN_ID,
        repository_root=REPOSITORY_ROOT,
    )

    assert {path: path.read_bytes() for path in paths} == before
