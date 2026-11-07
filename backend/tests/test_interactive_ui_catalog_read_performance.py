from __future__ import annotations

import sys
from pathlib import Path

import httpx

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_interactive_ui_catalog_read_performance import _check, scenarios  # noqa: E402


def test_named_catalog_and_evidence_cases_cover_in_scope_inventory() -> None:
    cases = scenarios()
    assert len(cases) == len({case.name for case in cases})
    assert len({case.route for case in cases}) == 9
    assert {case.name for case in cases} >= {
        "catalog_empty",
        "catalog_hard",
        "recording_detail_hard",
        "recording_detail_missing",
        "repository_bundle_hard",
        "analysis_missing",
        "counterfactual_missing",
        "timeline_missing",
        "table_observation_missing",
        "evidence_package_missing",
        "evidence_package_observations_missing",
    }


def test_correctness_oracle_checks_status_identity_and_error_code() -> None:
    catalog = next(case for case in scenarios() if case.name == "catalog_empty")
    assert _check(catalog, httpx.Response(200, json={"recordings": []})) is None
    assert _check(
        catalog, httpx.Response(200, json={"recordings": [{"recording_id": "other"}]})
    ) == ("expected recordings=[]; got [{'recording_id': 'other'}]")
    missing = next(case for case in scenarios() if case.name == "analysis_missing")
    assert (
        _check(missing, httpx.Response(404, json={"error": {"code": "analysis_not_found"}})) is None
    )
    assert _check(missing, httpx.Response(404, json={"error": {"code": "wrong"}})) == (
        "expected error code analysis_not_found; got {'code': 'wrong'}"
    )
