from __future__ import annotations

import sys
from pathlib import Path

import httpx

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_interactive_ui_pipeline_read_performance import _check, scenarios  # noqa: E402


def test_named_pipeline_cases_cover_inventory_and_hard_dimensions() -> None:
    cases = scenarios()
    assert len(cases) == len({case.name for case in cases})
    assert len({case.route for case in cases}) == 6
    assert {case.name for case in cases} == {
        "workspace_full_hard",
        "workspace_stage_visual_identities_hard",
        "workspace_missing",
        "lineage_hard",
        "lineage_missing",
        "revision_max_identity_payload",
        "revision_max_polygon_payload",
        "revision_missing_stale",
        "reviews_exact_revision",
        "reviews_stale_revision",
        "calibration_draft_snapshot",
        "calibration_draft_invalid_lineage",
        "calibration_draft_missing",
        "calibration_published_snapshot",
        "calibration_published_missing",
    }


def test_revision_correctness_checks_exact_fixture_identity_and_stale_errors() -> None:
    identity = next(case for case in scenarios() if case.name == "revision_max_identity_payload")
    payload = {
        "node_id": "e0d2e2fb-53ab-59c5-8991-3aba74f828ae",
        "revision_id": "f78c1e0a-2c0f-5312-98d6-b0b9b6650c0e",
        "content": {"items": [{"id": "x"}]},
    }
    assert _check(identity, httpx.Response(200, json=payload)) is None
    assert (
        _check(identity, httpx.Response(200, json={**payload, "revision_id": "stale"}))
        == "revision node or revision identity mismatch"
    )
    stale = next(case for case in scenarios() if case.name == "revision_missing_stale")
    assert (
        _check(stale, httpx.Response(404, json={"error": {"code": "pipeline_node_not_found"}}))
        is None
    )


def test_workspace_and_calibration_correctness_contracts() -> None:
    workspace = next(case for case in scenarios() if case.name == "workspace_full_hard")
    payload = {
        "schema_version": "pipeline-workspace/v1",
        "recording_id": "game-2026-08-20-01-001",
        "stages": [{}, {}, {}, {}, {}],
    }
    assert _check(workspace, httpx.Response(200, json=payload)) is None
    calibration = next(
        case for case in scenarios() if case.name == "calibration_published_snapshot"
    )
    assert (
        _check(
            calibration,
            httpx.Response(
                200,
                json={
                    "calibration_revision_id": "calibration-cd1069b46e30480b057d90b0",
                    "recording_id": "cardeventnet-IMG_0655",
                },
            ),
        )
        is None
    )


def test_calibration_draft_case_reports_stored_legacy_lineage_validation():
    draft = next(case for case in scenarios() if case.name == "calibration_draft_invalid_lineage")
    response = httpx.Response(
        422,
        json={
            "error": {
                "code": "invalid_calibration_refinement",
                "message": "proposal node lineage is invalid",
                "details": [],
            }
        },
    )
    assert _check(draft, response) is None


def test_calibration_draft_snapshot_checks_exact_fixture_identity():
    draft = next(case for case in scenarios() if case.name == "calibration_draft_snapshot")
    payload = {
        "recording_id": "cardeventnet-IMG_0655",
        "proposal_revision_id": (
            "card-scene-proposals-card-scene-proposal-0086-91x59-IMG_0655-retry-65bb8ec7-attempt-1"
        ),
        "draft": {
            "draft_id": (
                "calibration-draft-card-scene-proposals-card-scene-proposal-0086-91x59-"
                "IMG_0655-retry-65bb8ec7-attempt-1"
            )
        },
    }
    assert _check(draft, httpx.Response(200, json=payload)) is None
    payload["draft"]["draft_id"] = "wrong-draft"
    assert _check(draft, httpx.Response(200, json=payload))
