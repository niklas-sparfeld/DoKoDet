from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import qualify_interactive_ui_performance as qualification  # noqa: E402


def test_route_match_accepts_inventory_parameters_and_exact_templates() -> None:
    assert qualification._route_matches(
        "/api/jobs/{job_id}/logs", "/api/jobs/550e8400-e29b-41d4-a716-446655440000/logs?after=0"
    )
    assert qualification._route_matches(
        "/api/recordings/{recording_id}/pipeline", "/api/recordings/{recording_id}/pipeline"
    )
    assert not qualification._route_matches("/api/jobs/{job_id}", "/api/jobs/one/logs")


def test_budget_uses_measured_noise_and_relative_ceiling() -> None:
    budget = qualification._stats(
        {"durations_ns": [100_000_000, 101_000_000, 99_000_000], "category": "control"}
    )
    assert budget["metric"] == "median"
    assert budget["median_ns"] == 100_000_000
    assert budget["absolute_noise_allowance_ns"] >= 2_000_000
    assert (
        budget["ceiling_ns"] == budget["reference_ns"] * 1.2 + budget["absolute_noise_allowance_ns"]
    )


def test_comparator_rejects_slow_candidate_and_missing_route(tmp_path: Path, monkeypatch) -> None:
    baseline = {
        "environment": {"machine": "test"},
        "cases": {
            "api/case": {"samples": 3, "reference_ns": 100, "ceiling_ns": 130, "metric": "median"}
        },
        "ui_routes": {"api:GET:/api/example": {"groups": ["api/case"], "ceiling_ns": 130}},
    }
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(baseline))
    monkeypatch.setattr(
        qualification,
        "make_baseline",
        lambda _results: {
            "environment": {"machine": "test"},
            "cases": {
                "api/case": {
                    "samples": 3,
                    "reference_ns": 1_000,
                    "ceiling_ns": 1_200,
                    "metric": "median",
                }
            },
            "ui_routes": {},
        },
    )
    errors = qualification.qualify(tmp_path, path)
    assert any("exceeds ceiling" in error for error in errors)
    assert any("UI route coverage differs" in error for error in errors)
