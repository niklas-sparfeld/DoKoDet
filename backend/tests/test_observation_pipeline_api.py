from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from app_factory import create_test_app
from fastapi.testclient import TestClient
from test_visible_card_pipeline_api import (
    RECORDING_ID,
    _Detector,
    _EventProvider,
    _FrameResolver,
    _install_recording,
    _settings,
)
from test_visual_identity_pipeline_api import _IdentityProvider


def test_observation_assembly_freezes_lineage_and_coexists_after_restart(
    tmp_path: Path,
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
        identity_revision_id = _run_pipeline(client, "identity-assembly", "visual-identities")

        first = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/observations",
            json={
                "run_id": "assembly-01",
                "input_revision_ids": [
                    event_revision_id,
                    visible_revision_id,
                    identity_revision_id,
                ],
            },
        )
        assert first.status_code == 202
        assert _wait_observation(client, "assembly-01")["state"]["status"] == "complete"
        first_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/observations/assembly-01/result"
        )
        assert first_result.status_code == 200
        first_body = first_result.json()
        assert first_body["request"]["input_revision_ids"] == [
            event_revision_id,
            visible_revision_id,
            identity_revision_id,
        ]
        content = first_body["revisions"][0]["content"]
        assert content["observations"][0]["status"] == "observed"
        assert content["observations"][0]["source"]["assembly_run_id"] == "assembly-01"
        assert content["observations"][0]["source"]["input_revision_ids"] == [
            event_revision_id,
            visible_revision_id,
            identity_revision_id,
        ]
        assert content["observations"][1]["status"] == "observed"
        assert content["observations"][2]["status"] == "insufficient_evidence"

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
        second_body = _wait_observation(client, "assembly-02")
        assert second_body["state"]["status"] == "complete"
        listed = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/observations"
        ).json()["runs"]
        assert {run["run_id"] for run in listed} >= {"assembly-01", "assembly-02"}
        selection = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/observations/selection"
        ).json()
        assert selection["selection"]["selected_generated_revision_id"] == second_body[
            "state"
        ]["output_revision_ids"][0]

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
            f"/api/recordings/{RECORDING_ID}/pipeline/observations/assembly-01/result"
        )
        assert persisted.status_code == 200
        assert persisted.json()["revisions"][0]["content"]["observations"][0]["source"][
            "assembly_run_id"
        ] == "assembly-01"


def _run_pipeline(
    client: TestClient,
    run_id: str,
    stage: str,
    *,
    configuration: dict[str, object] | None = None,
) -> str:
    payload: dict[str, object] = {"run_id": run_id}
    if configuration is not None:
        payload["configuration"] = configuration
    response = client.post(
        f"/api/recordings/{RECORDING_ID}/pipeline/{stage}", json=payload
    )
    assert response.status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        body = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/{stage}/{run_id}"
        ).json()
        if body["state"]["status"] == "complete":
            return body["state"]["output_revision_ids"][0]
        assert body["state"]["status"] != "failed", body
        time.sleep(0.01)
    raise AssertionError(f"{stage} run did not complete")


def _wait_observation(client: TestClient, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        body = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/observations/{run_id}"
        ).json()
        if body["state"]["status"] in {"complete", "failed"}:
            return body
        time.sleep(0.01)
    return body


def test_recording_analysis_uses_selected_observations_without_evidence_packages(
    tmp_path: Path,
) -> None:
    _install_recording(tmp_path)
    _make_analysis_metadata(tmp_path)
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
        _run_pipeline(client, "analysis-visible-01", "visible-cards")
        _run_pipeline(client, "analysis-identity-01", "visual-identities")
        first_revision_id = _run_pipeline(
            client,
            "analysis-observation-01",
            "observations",
            configuration={"session_id": "6ba7b810-9dad-41d1-80b4-00c04fd430c8"},
        )

        first = client.post(f"/v1/recordings/{RECORDING_ID}/round-analyses")
        assert first.status_code == 202, first.text
        first_body = first.json()
        assert first_body["state"] == "complete"
        first_analysis_id = first_body["analysis_id"]
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
        assert timeline.json()["rows"][0]["package_id"] is None

        second_revision_id = _run_pipeline(
            client,
            "analysis-observation-02",
            "observations",
            configuration={"session_id": "6ba7b810-9dad-41d1-80b4-00c04fd430c8"},
        )
        assert second_revision_id != first_revision_id
        second = client.post(f"/v1/recordings/{RECORDING_ID}/round-analyses")
        assert second.status_code == 202, second.text
        assert second.json()["state"] == "complete"
        assert second.json()["analysis_id"] != first_analysis_id


def _make_analysis_metadata(tmp_path: Path) -> None:
    """Give the shared pipeline fixture UUID session metadata for round analysis."""

    bundle = tmp_path / "recordings" / RECORDING_ID
    manifest_path = bundle / "manifest.json"
    source_path = bundle / "source-record.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = json.loads(source_path.read_text(encoding="utf-8"))
    session_id = "6ba7b810-9dad-41d1-80b4-00c04fd430c8"
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
