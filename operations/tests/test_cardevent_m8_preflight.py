from __future__ import annotations

import json
from pathlib import Path

import pytest

from doko_operations.cardevent_campaign import (
    CardEventCampaignError,
    _validate_interval_selection_configuration,
    preflight_card_event_campaign,
)
from doko_operations.model_improvement import load_model_recipe

REPOSITORY_ROOT = Path(__file__).parents[2]
RECIPE_PATH = REPOSITORY_ROOT / "experiments" / "cardevent" / "0063-m8-interval-validation.yaml"


def test_m8_recipe_declares_one_fixed_interval_axis_and_checkpoint() -> None:
    recipe = load_model_recipe(RECIPE_PATH)

    assert recipe.recipe_id == "cardeventnet-0063-m8-interval-validation"
    assert recipe.baseline_checkpoint is not None
    assert recipe.baseline_checkpoint.id.startswith("checkpoint-cardeventnet-0063-m5")
    assert recipe.data.dataset.id == "cardeventnet-interval-dataset-2e00fe87f08e25c51aa4"
    assert recipe.data.split.id == "cardeventnet-interval-split-99ff7cb84e5484c7b4a1"
    assert recipe.seeds == (42,)
    assert recipe.budget.max_candidates == 1
    assert recipe.sealed_test_authorized is False
    assert recipe.candidates[0].configuration["decoder_settings"] == {
        "peak_confirmation_s": 0.125,
        "min_event_gap_s": 0.625,
    }


def test_m8_preflight_writes_handoff_without_campaign_execution() -> None:
    handoff_path = REPOSITORY_ROOT / ".runtime" / "cardevent" / "m8-test-handoff.json"
    campaign_path = (
        REPOSITORY_ROOT
        / "data"
        / "model-campaigns"
        / "cardeventnet-0063-m8-interval-validation-df1dddc98bbb"
        / "campaign.json"
    )
    campaign_before = campaign_path.read_bytes() if campaign_path.exists() else None
    handoff = preflight_card_event_campaign(
        RECIPE_PATH,
        repository_root=REPOSITORY_ROOT,
        handoff_path=handoff_path,
    )

    assert handoff["status"] == "ready"
    assert handoff["selection"] == {
        "training_partition": "train",
        "validation_partition": "val",
        "test_partition": "sealed_not_read",
        "system_holdout": "not_read",
        "hard_negatives": "not_used",
        "sample_estimate": handoff["selection"]["sample_estimate"],
    }
    assert handoff["selection"]["sample_estimate"]["train"]["selected_samples"] == 12878
    assert handoff["selection"]["sample_estimate"]["validation"]["selected_samples"] == 3017
    assert "--dataset-view" in handoff["commands"]["training"]
    assert "--hard-negative-manifest" not in handoff["commands"]["training"]
    assert "partition test" not in handoff["commands"]["training"]
    assert (campaign_path.read_bytes() if campaign_path.exists() else None) == campaign_before
    written = json.loads(handoff_path.read_text(encoding="utf-8"))
    assert written["handoff_digest"] == handoff["handoff_digest"]


@pytest.mark.parametrize(
    ("key", "value", "message"),
    (
        ("hard_negative_manifest", "data/hard-negatives.json", "hard-negative"),
        ("system_holdout_path", "data/system-holdout.json", "system holdout"),
        ("partition", "test", "partition"),
    ),
)
def test_m8_selection_rejects_test_holdout_and_hard_negative_inputs(
    key: str, value: object, message: str
) -> None:
    with pytest.raises(CardEventCampaignError, match=message):
        _validate_interval_selection_configuration({key: value})
