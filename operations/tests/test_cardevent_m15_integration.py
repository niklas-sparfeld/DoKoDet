from __future__ import annotations

import json
from pathlib import Path

import doko_operations.cardevent_m15 as m15

REPOSITORY_ROOT = Path(__file__).parents[2]
CAMPAIGN_DIR = (
    REPOSITORY_ROOT
    / "data"
    / "model-campaigns"
    / "cardeventnet-0063-m14-development-integration"
)


def test_m15_closes_the_campaign_without_changing_the_champion(monkeypatch) -> None:
    runtime = json.loads((CAMPAIGN_DIR / "runtime-checks.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(m15, "_run_runtime_parity", lambda root, checkpoint, bundle: runtime)

    result = m15.validate_cardeventnet_m15_integration(
        m15.M15_CAMPAIGN_ID,
        repository_root=REPOSITORY_ROOT,
    )

    assert result["state"] == "closed"
    assert result["outcome"] == "m9_retained_as_development_integration_baseline"
    assert result["sealed_test"]["partition"] == "test"
    assert result["sealed_test"]["metrics"]["event_recall"] == 0.8283261802575107
    assert result["production_promotion_eligible"] is False
    assert result["current_champion_changed"] is False
    assert result["promotion_receipt_written"] is False
    assert result["legacy_device_diagnostic"]["gating"] is False


def test_m15_closeout_artifacts_are_reproducible(monkeypatch) -> None:
    runtime = json.loads((CAMPAIGN_DIR / "runtime-checks.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(m15, "_run_runtime_parity", lambda root, checkpoint, bundle: runtime)
    paths = (
        CAMPAIGN_DIR / "current-champion.json",
        CAMPAIGN_DIR / "integration-contract.json",
        CAMPAIGN_DIR / "m15-result.json",
        CAMPAIGN_DIR / "m15-report.md",
        CAMPAIGN_DIR / "runtime-checks.json",
    )
    before = {path: path.read_bytes() for path in paths}

    m15.validate_cardeventnet_m15_integration(
        m15.M15_CAMPAIGN_ID,
        repository_root=REPOSITORY_ROOT,
    )

    assert {path: path.read_bytes() for path in paths} == before
