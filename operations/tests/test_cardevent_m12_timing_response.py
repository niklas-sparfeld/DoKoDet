from __future__ import annotations

import json
from pathlib import Path

import yaml

from doko_operations.cardevent_m12 import (
    M12_RESPONSE_ID,
    prepare_cardeventnet_m12_timing_response,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
SOURCE_CAMPAIGN_ID = "cardeventnet-0063-m9-hard-negative-ablation"
CAMPAIGN_DIR = (
    REPOSITORY_ROOT / "data" / "model-campaigns" / "cardeventnet-0063-m12-timing-response"
)


def test_m12_selects_one_endpoint_response_without_starting_training() -> None:
    result = prepare_cardeventnet_m12_timing_response(
        SOURCE_CAMPAIGN_ID,
        repository_root=REPOSITORY_ROOT,
    )
    handoff = json.loads((CAMPAIGN_DIR / "m12-result.json").read_text(encoding="utf-8"))

    assert result["response"]["response_id"] == M12_RESPONSE_ID
    assert handoff["response_selection"]["candidates_considered"] == [M12_RESPONSE_ID]
    assert handoff["response_selection"]["selected_response"] == M12_RESPONSE_ID
    assert handoff["training_started"] is False
    assert handoff["sealed_test_read"] is False
    assert handoff["system_holdout_read"] is False
    assert "--partition test" not in handoff["commands"]["prepare_train_and_validation_cache"]
    assert "test" not in handoff["commands"]["evaluate_validation"]

    baseline = yaml.safe_load(
        (
            REPOSITORY_ROOT / "card_event_net" / "configs" / "transition-label-v2.yaml"
        ).read_text(encoding="utf-8")
    )
    response = yaml.safe_load(
        (CAMPAIGN_DIR / "interval-endpoint-focus-v1.yaml").read_text(encoding="utf-8")
    )
    assert response["labels"]["positive_window_s"] == 0.125
    response["labels"].pop("positive_window_s")
    baseline["labels"].pop("positive_window_s")
    assert response == baseline


def test_m12_handoff_is_reproducible() -> None:
    paths = (
        CAMPAIGN_DIR / "interval-endpoint-focus-v1.yaml",
        CAMPAIGN_DIR / "m12-result.json",
        CAMPAIGN_DIR / "m12-report.md",
    )
    before = {path: path.read_bytes() for path in paths}

    prepare_cardeventnet_m12_timing_response(
        SOURCE_CAMPAIGN_ID,
        repository_root=REPOSITORY_ROOT,
    )

    assert {path: path.read_bytes() for path in paths} == before
