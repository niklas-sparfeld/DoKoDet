from __future__ import annotations

from pathlib import Path
from runpy import run_path

import pytest

ROOT = Path(__file__).resolve().parents[2]
M13 = run_path(str(ROOT / "operations/scripts/run_0088_m13_final_evaluation.py"))


def test_m12_lock_validates_with_both_finalists() -> None:
    lock = M13["read_json"](M13["LOCK_DEFAULT"])

    M13["_validate_lock"](lock)

    assert {candidate["candidate_id"] for candidate in lock["candidates"]} == {
        "m3-seed17-224-cls",
        "m6-seed17-224-cls-mean-patch",
    }


def test_missing_gemini_key_stops_before_final_test_access(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    output = tmp_path / "m13-output"

    with pytest.raises(ValueError, match="stopped before opening or scoring"):
        M13["run"](M13["LOCK_DEFAULT"], output, "mps")

    assert not output.exists()


def test_final_metrics_keep_failed_predictions_in_denominator() -> None:
    rows = [
        {
            "target": "HEARTS_ACE",
            "prediction": "HEARTS_ACE",
            "source_group_id": "one-group",
            "frame_key": "frame-a",
            "usable": True,
        },
        {
            "target": "HEARTS_ACE",
            "prediction": "UNAVAILABLE",
            "source_group_id": "one-group",
            "frame_key": "frame-b",
            "usable": False,
        },
    ]

    result = M13["metrics"](rows, is_dino=False)

    assert result["sample_count"] == 2
    assert result["top_1_accuracy"] == 0.5
    assert result["usable_prediction_coverage"] == 0.5
    assert result["grouped_uncertainty"]["interval"] is None
