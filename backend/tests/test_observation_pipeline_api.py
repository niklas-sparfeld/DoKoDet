from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app_factory import create_test_app
from doko_operations.pipeline_data import sha256_bytes
from fastapi.testclient import TestClient
from table_evidence_analyzer import ObservationAssemblyError
from table_evidence_analyzer.pipeline_data import (
    VisibleCardPileRegion,
    canonical_visible_card_data_bytes,
)
from test_visible_card_pipeline_api import (
    RECORDING_ID,
    _Detector,
    _EventProvider,
    _FrameResolver,
    _install_recording,
    _run_event_job,
    _selected_node_input,
    _settings,
)
from test_visual_identity_pipeline_api import _IdentityProvider

import dokodetector_backend.observation_pipeline_service as observation_service_module


def test_observation_assembly_freezes_lineage_and_coexists_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_recording(tmp_path)
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=_IdentityProvider(),
    )

    with TestClient(app) as client:
        event_revision_id = _run_pipeline(client, "events-assembly", "events")
        visible_revision_id = _run_pipeline(client, "visible-assembly", "visible-cards")
        generated_visible_revision_id = visible_revision_id
        stored_visible = app.state.pipeline_revision_store.require(visible_revision_id)
        pile = VisibleCardPileRegion.from_mapping(
            {
                "pile_id": "pile-observation-fixture",
                "geometry": {
                    "kind": "pile-region/v1",
                    "polygons": [
                        [
                            {"x": 100, "y": 200},
                            {"x": 400, "y": 200},
                            {"x": 400, "y": 600},
                            {"x": 100, "y": 600},
                        ]
                    ],
                },
                "normalization": {
                    "width": 64,
                    "height": 64,
                    "policy_id": "full-frame-0-1000/v1",
                },
                "source_candidates": [],
                "origin": "model_prediction",
                "confidence": 0.91,
                "model_lineage": {"bundle_id": "pile-observation-fixture"},
            }
        )
        pile_visible_content = replace(
            stored_visible.content,
            outcomes=tuple(
                replace(outcome, pile_regions=(pile,))
                if outcome is stored_visible.content.outcomes[0]
                else outcome
                for outcome in stored_visible.content.outcomes
            ),
        )
        pile_visible_manifest = replace(
            stored_visible.manifest,
            revision_id="visible-assembly-with-pile",
            content_sha256=sha256_bytes(canonical_visible_card_data_bytes(pile_visible_content)),
        )
        app.state.pipeline_revision_store.publish(pile_visible_manifest, pile_visible_content)
        visible_revision_id = "visible-assembly-with-pile"
        node_store = app.state.visible_card_pipeline_service.node_store
        visible_node = next(
            node
            for node in node_store.list_nodes()
            if any(
                revision.metadata.get("legacy_revision_id") == generated_visible_revision_id
                for revision in node_store.history(node.node_id)
            )
        )
        visible_node_head = node_store.get(visible_node.node_id).head_revision_id
        node_store.save(
            visible_node.node_id,
            visible_node_head,
            pile_visible_content.to_mapping(),
            {
                "legacy_revision_id": visible_revision_id,
                "legacy_content_sha256": pile_visible_manifest.content_sha256,
            },
        )
        identity_revision_id = _run_pipeline(
            client,
            "identity-assembly",
            "visual-identities",
            input_revision_ids=[visible_revision_id],
        )
        identity_revision = app.state.pipeline_revision_store.require(identity_revision_id)
        node_store.create(
            "fixture-assembly-identity-node",
            "Generated visual identities",
            "visual_identities",
            identity_revision.manifest.source.to_mapping(),
            identity_revision.content.to_mapping(),
            {
                "legacy_revision_id": identity_revision_id,
                "legacy_content_sha256": identity_revision.manifest.content_sha256,
                "legacy_content_schema": identity_revision.manifest.content_schema,
            },
            revision_id=identity_revision_id,
        )

        workspace = client.get(f"/api/recordings/{RECORDING_ID}/pipeline")
        assert workspace.status_code == 200
        compatible_input_set = {
            "input_revision_ids": [
                event_revision_id,
                generated_visible_revision_id,
                identity_revision_id,
            ],
            "display_label": (
                "Generated events + Generated visible cards + Generated visual identities"
            ),
        }
        assert compatible_input_set in workspace.json()["stages"][3]["compatible_input_sets"]

        first = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/observations",
            json={
                "request": {
                    "run_id": "assembly-01",
                    "input_revision_ids": [
                        event_revision_id,
                        visible_revision_id,
                        identity_revision_id,
                    ],
                }
            },
        )
        assert first.status_code == 202, first.text
        assembly_first_id = first.json()["run_id"]
        assert _wait_observation(client, assembly_first_id)["state"]["status"] == "complete"
        first_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/observations/{assembly_first_id}/result"
        )
        assert first_result.status_code == 200
        first_body = first_result.json()
        assert first_body["request"]["input_revision_ids"] == [
            event_revision_id,
            visible_revision_id,
            identity_revision_id,
        ]
        node_refs = first_body["request"]["input_node_refs"]
        assert len(node_refs) == 3
        assert len({ref["node_id"] for ref in node_refs}) == 3
        assert all(ref["revision_id"] for ref in node_refs)
        assert [ref["revision_policy"] for ref in node_refs] == ["historical"] * 3
        content = first_body["revisions"][0]["content"]
        assert content["observations"][0]["status"] == "observed"
        assert content["observations"][0]["schema_version"] == "table-observation/v2"
        assert content["observations"][0]["piles"][0]["pile_id"] == "pile-observation-fixture"
        assert content["observations"][0]["piles"][0]["model_lineage"] == {
            "bundle_id": "pile-observation-fixture"
        }
        assert content["observations"][0]["source"]["assembly_run_id"] == assembly_first_id
        assert content["observations"][0]["source"]["input_revision_ids"] == [
            event_revision_id,
            visible_revision_id,
            identity_revision_id,
        ]
        assert content["observations"][1]["status"] == "observed"
        assert content["observations"][1]["cards"] == []
        assert content["observations"][2]["status"] == "insufficient_evidence"

        deadline = time.monotonic() + 5
        lineage = app.state.pipeline_lineage_service.snapshot(RECORDING_ID)
        lineage_runs = {item["run_id"]: item for item in lineage["runs"]}
        while (
            time.monotonic() < deadline
            and lineage_runs.get(assembly_first_id, {}).get("status") == "accepted"
        ):
            time.sleep(0.01)
            lineage = app.state.pipeline_lineage_service.snapshot(RECORDING_ID)
            lineage_runs = {item["run_id"]: item for item in lineage["runs"]}
        assert len(lineage_runs) >= 4
        assert assembly_first_id in lineage_runs
        assert lineage_runs[assembly_first_id]["status"] == "succeeded"
        assert {item["role"] for item in lineage_runs[assembly_first_id]["inputs"]} == {
            "events",
            "visible_cards",
            "visual_identities",
        }
        assert (
            lineage_runs[assembly_first_id]["outputs"][0]["revision_id"]
            == first_body["revisions"][0]["manifest"]["revision_id"]
        )

        accepted_job = client.get(f"/api/jobs/{assembly_first_id}").json()
        assert [item["id"] for item in accepted_job["inputs"]] == [
            event_revision_id,
            visible_revision_id,
            identity_revision_id,
        ]
        assert [item["digest"] for item in accepted_job["inputs"]] == [
            app.state.pipeline_revision_store.require(revision_id).manifest.content_sha256
            for revision_id in (event_revision_id, visible_revision_id, identity_revision_id)
        ]

        original_assembler = observation_service_module.assemble_table_observations
        calls = 0

        def fail_accepted_execution(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls == 1:
                return original_assembler(*args, **kwargs)
            raise ObservationAssemblyError("fixture execution failure")

        monkeypatch.setattr(
            observation_service_module, "assemble_table_observations", fail_accepted_execution
        )
        failed = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/observations",
            json={
                "run_id": "assembly-retry-source",
                "input_revision_ids": [
                    event_revision_id,
                    visible_revision_id,
                    identity_revision_id,
                ],
            },
        )
        assert failed.status_code == 202, failed.text
        failed_job_id = failed.json()["run_id"]
        assert _wait_observation(client, failed_job_id)["state"]["status"] == "failed"
        monkeypatch.setattr(
            observation_service_module, "assemble_table_observations", original_assembler
        )
        deadline = time.monotonic() + 5
        failed_job = client.get(f"/api/jobs/{failed_job_id}").json()
        while time.monotonic() < deadline and failed_job["state"] not in {
            "failed",
            "cancelled",
            "interrupted",
        }:
            time.sleep(0.01)
            failed_job = client.get(f"/api/jobs/{failed_job_id}").json()
        assert failed_job["state"] == "failed", failed_job
        retried = client.post(
            f"/api/jobs/{failed_job_id}/retry",
            headers={"Idempotency-Key": str(uuid4())},
            json={},
        )
        assert retried.status_code == 202, retried.text
        retry_job_id = retried.json()["id"]
        assert retry_job_id != failed_job_id
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            retry_job = client.get(f"/api/jobs/{retry_job_id}").json()
            if retry_job["state"] == "succeeded":
                break
            assert retry_job["state"] not in {"failed", "cancelled", "interrupted"}, retry_job
            time.sleep(0.01)
        assert retry_job["state"] == "succeeded", retry_job
        retried_run = app.state.pipeline_run_store.require(retry_job_id)
        assert retried_run.request.input_revision_ids == (
            event_revision_id,
            visible_revision_id,
            identity_revision_id,
        )

        second = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/observations",
            json={
                "run_id": "assembly-02",
                "input_revision_ids": [
                    event_revision_id,
                    visible_revision_id,
                    identity_revision_id,
                ],
            },
        )
        assert second.status_code == 202
        assembly_second_id = second.json()["run_id"]
        second_body = _wait_observation(client, assembly_second_id)
        assert second_body["state"]["status"] == "complete"
        listed = client.get(f"/api/recordings/{RECORDING_ID}/pipeline/observations").json()["runs"]
        assert {run["run_id"] for run in listed} >= {assembly_first_id, assembly_second_id}
        selection = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/observations/selection"
        ).json()
        deadline = time.monotonic() + 5
        while (
            selection["selection"]["selected_generated_revision_id"]
            != second_body["state"]["output_revision_ids"][0]
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
            selection = client.get(
                f"/api/recordings/{RECORDING_ID}/pipeline/observations/selection"
            ).json()
        assert (
            selection["selection"]["selected_generated_revision_id"]
            == second_body["state"]["output_revision_ids"][0]
        )

        mismatch = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/observations",
            json={
                "run_id": "assembly-mismatch",
                "event_revision_id": event_revision_id,
                "visible_card_revision_id": visible_revision_id,
                "visual_identity_revision_id": "missing-revision",
            },
        )
        assert mismatch.status_code == 404

    restarted = create_test_app(_settings(tmp_path))
    with TestClient(restarted) as client:
        persisted = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/observations/{assembly_first_id}/result"
        )
        assert persisted.status_code == 200
        assert (
            persisted.json()["revisions"][0]["content"]["observations"][0]["source"][
                "assembly_run_id"
            ]
            == assembly_first_id
        )
        persisted_observation = persisted.json()["revisions"][0]["content"]["observations"][0]
        assert persisted_observation["piles"][0]["pile_id"] == "pile-observation-fixture"
        assert persisted_observation["piles"][0]["confidence"] == 0.91


def _run_pipeline(
    client: TestClient,
    run_id: str,
    stage: str,
    *,
    configuration: dict[str, object] | None = None,
    input_revision_ids: list[str] | None = None,
) -> str:
    payload: dict[str, object] = {"run_id": run_id}
    if configuration is not None:
        payload["configuration"] = configuration
    if input_revision_ids is not None:
        payload["input_revision_ids"] = input_revision_ids
    if stage == "events":
        return _run_event_job(client, run_id)
    if stage == "visible-cards" and input_revision_ids is None:
        payload.update(_selected_node_input(client, "events"))
    response = client.post(f"/api/recordings/{RECORDING_ID}/pipeline/{stage}", json=payload)
    assert response.status_code == 202, response.text
    managed_run_id = response.json()["run_id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        body = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/{stage}/{managed_run_id}"
        ).json()
        if body["state"]["status"] == "complete":
            return body["state"]["output_revision_ids"][0]
        assert body["state"]["status"] != "failed", body
        time.sleep(0.01)
    raise AssertionError(f"{stage} run did not complete")


def _run_observation(client: TestClient, run_id: str) -> tuple[str, str]:
    response = client.post(
        f"/api/recordings/{RECORDING_ID}/pipeline/observations",
        json={"run_id": run_id},
    )
    assert response.status_code == 202, response.text
    managed_run_id = response.json()["run_id"]
    body = _wait_observation(client, managed_run_id)
    assert body["state"]["status"] == "complete", body
    return managed_run_id, body["state"]["output_revision_ids"][0]


def _wait_observation(client: TestClient, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        body = client.get(f"/api/recordings/{RECORDING_ID}/pipeline/observations/{run_id}").json()
        if body["state"]["status"] in {"complete", "failed"}:
            return body
        time.sleep(0.01)
    return body


@pytest.mark.parametrize(
    "session_id", ["6ba7b810-9dad-41d1-80b4-00c04fd430c8", "session-2026-08-20"]
)
def test_recording_analysis_uses_selected_observations_without_evidence_packages(
    tmp_path: Path, session_id: str
) -> None:
    _install_recording(tmp_path)
    _make_analysis_metadata(tmp_path, session_id=session_id)
    app = create_test_app(
        _settings(tmp_path),
        run_round_analysis_synchronously=True,
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=_IdentityProvider(),
    )

    with TestClient(app) as client:
        _run_pipeline(client, "analysis-assembly-01", "events")
        visible_revision_id = _run_pipeline(client, "analysis-visible-01", "visible-cards")
        _run_pipeline(
            client,
            "analysis-identity-01",
            "visual-identities",
            input_revision_ids=[visible_revision_id],
        )
        rejected_override = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/observations",
            json={
                "run_id": "analysis-observation-conflict",
                "configuration": {"session_id": "wrong-session"},
            },
        )
        assert rejected_override.status_code == 422
        assert "must match the recording session ID" in rejected_override.text
        observation_run_id, first_revision_id = _run_observation(
            client,
            "analysis-observation-01",
        )
        observation = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/observations/{observation_run_id}/result"
        ).json()["revisions"][0]["content"]["observations"][0]
        assert observation["session"]["session_id"] == session_id

        first = client.post(f"/v1/recordings/{RECORDING_ID}/round-analyses")
        assert first.status_code == 422
        first = client.post(
            "/v1/round-analyses",
            json={
                "analysis_id": "550e8400-e29b-41d4-a716-446655440081",
                "recording_id": RECORDING_ID,
                "round_id": "round-assembly",
                "session_id": session_id,
                "table_observation_revision_id": first_revision_id,
                "round_context": {
                    "game_id": "game-assembly",
                    "round_id": "round-assembly",
                    "active_players": ["north", "east", "south", "west"],
                    "dealer": "east",
                    "first_trick_leader": "south",
                },
                "rules_version": "v1",
                "search": {
                    "max_missing_plays": 1,
                    "max_hypotheses": 8,
                    "max_search_nodes": 1000,
                },
            },
        )
        assert first.status_code == 202, first.text
        first_body = first.json()
        assert first_body["state"] == "complete"
        assert first_body["session_id"] == session_id
        assert first_body["round_context"]["active_players"] == [
            "north",
            "east",
            "south",
            "west",
        ]
        first_analysis_id = first_body["analysis_id"]
        status = client.get(f"/v1/round-analyses/{first_analysis_id}")
        assert status.status_code == 200
        assert status.json()["session_id"] == session_id
        assert status.json()["round_context"]["dealer"] == "east"
        assert status.json()["round_context"]["active_players"] == [
            "north",
            "east",
            "south",
            "west",
        ]
        assert first_body["total_evidence_packages"] == 0
        input_path = (
            app.state.round_analysis_storage.analysis_path(first_analysis_id)
            / "inputs"
            / "table-observations.json"
        )
        assert input_path.is_file()
        assert json.loads(input_path.read_text(encoding="utf-8"))["schema_version"] == (
            "table-observation-data/v1"
        )
        timeline = client.get(f"/v1/round-analyses/{first_analysis_id}/timeline")
        assert timeline.status_code == 200, timeline.text
        assert timeline.json()["session_id"] == session_id
        assert timeline.json()["rows"][0]["package_id"] is None
        counterfactual_id = "550e8400-e29b-41d4-a716-446655440099"
        counterfactual_payload = {
            "schema_version": "round-analysis-counterfactual/v1",
            "counterfactual_id": counterfactual_id,
            "source_analysis_id": first_analysis_id,
            "source_input_sha256": first_body["result"]["input_artifact_sha256"],
            "source_result_sha256": first_body["result"]["result_artifact_sha256"],
            "excluded_observation_ids": [timeline.json()["rows"][0]["observation_id"]],
            "excluded_observed_cards": [],
            "card_identity_overrides": [],
            "candidate_probability_overrides": [],
        }
        counterfactual_job = client.post(
            "/api/jobs",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "type": "counterfactual",
                "context": {"analysis_id": first_analysis_id},
                "request": counterfactual_payload,
            },
        )
        assert counterfactual_job.status_code == 202, counterfactual_job.text
        counterfactual_job_id = counterfactual_job.json()["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            counterfactual_status = client.get(f"/api/jobs/{counterfactual_job_id}").json()
            if counterfactual_status["state"] == "succeeded":
                break
            assert counterfactual_status["state"] not in {
                "failed",
                "cancelled",
                "interrupted",
            }, counterfactual_status
            time.sleep(0.01)
        assert counterfactual_status["state"] == "succeeded", counterfactual_status
        counterfactual_read = client.get(
            f"/v1/round-analyses/{first_analysis_id}/counterfactuals/{counterfactual_id}"
        )
        assert counterfactual_read.status_code == 200
        assert counterfactual_read.json()["counterfactual_id"] == counterfactual_id

        second_revision_id = _run_pipeline(
            client,
            "analysis-observation-02",
            "observations",
        )
        assert second_revision_id != first_revision_id
        second = client.post(f"/v1/recordings/{RECORDING_ID}/round-analyses")
        assert second.status_code == 202, second.text
        assert second.json()["state"] == "complete"
        assert second.json()["analysis_id"] != first_analysis_id
        assert second.json()["round_context"] == first_body["round_context"]

    restarted = create_test_app(_settings(tmp_path), run_round_analysis_synchronously=True)
    with TestClient(restarted) as client:
        status = client.get(f"/v1/round-analyses/{first_analysis_id}")
        timeline = client.get(f"/v1/round-analyses/{first_analysis_id}/timeline")
        counterfactual = client.get(
            f"/v1/round-analyses/{first_analysis_id}/counterfactuals/{counterfactual_id}"
        )
        assert status.status_code == 200
        assert status.json()["session_id"] == session_id
        assert timeline.status_code == 200
        assert timeline.json()["session_id"] == session_id
        assert counterfactual.status_code == 200


def _make_analysis_metadata(tmp_path: Path, *, session_id: str) -> None:
    """Give the shared pipeline fixture canonical session metadata for round analysis."""

    bundle = tmp_path / "recordings" / RECORDING_ID
    manifest_path = bundle / "manifest.json"
    source_path = bundle / "source-record.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = json.loads(source_path.read_text(encoding="utf-8"))
    manifest["session_id"] = session_id
    source["session_id"] = session_id
    source["round_id"] = f"round-{RECORDING_ID}"
    source_bytes = json.dumps(source, separators=(",", ":")).encode("utf-8")
    source_path.write_bytes(source_bytes)
    manifest["files"]["source_record"].update(
        byte_length=len(source_bytes),
        sha256=hashlib.sha256(source_bytes).hexdigest(),
    )
    manifest_path.write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
