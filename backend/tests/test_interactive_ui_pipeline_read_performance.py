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
    assert len({(case.method, case.route) for case in cases}) == 23
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
        "event_runs_exact",
        "event_result_exact",
        "event_result_missing",
        "observation_result_missing",
        "proposed_scene_result_missing",
        "visible_card_result_missing",
        "visual_identity_result_missing",
        "observation_runs_empty",
        "proposed_scene_runs_empty",
        "visible_card_runs_empty",
        "visual_identity_runs_empty",
        "event_selection_exact",
        "observation_selection_empty",
        "visible_card_selection_empty",
        "visual_identity_selection_empty",
        "visual_identity_proposed_inputs_empty",
        "automated_run_missing",
        "automated_run_exact",
        "comparison_missing_inputs",
        "comparison_exact_runs",
    }


def test_pipeline_read_cases_check_empty_identity() -> None:
    cases = {case.name: case for case in scenarios()}
    assert (
        _check(
            cases["observation_runs_empty"],
            httpx.Response(200, json={"recording_id": "game-2026-08-20-01-001", "runs": []}),
        )
        is None
    )
    assert (
        _check(
            cases["observation_runs_empty"],
            httpx.Response(200, json={"recording_id": "other-recording", "runs": []}),
        )
        == "pipeline run list identity or sparse content mismatch"
    )


def test_run_and_comparison_missing_cases_check_exact_error_codes() -> None:
    cases = {case.name: case for case in scenarios()}
    assert (
        _check(
            cases["automated_run_missing"],
            httpx.Response(404, json={"error": {"code": "pipeline_run_not_found"}}),
        )
        is None
    )
    assert (
        _check(
            cases["comparison_missing_inputs"],
            httpx.Response(404, json={"error": {"code": "comparison_input_not_found"}}),
        )
        is None
    )


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
