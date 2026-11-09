"""M4 real-API proof for recording-owned current state."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.pipeline_node_uses import PipelineNodeUses
from dokodetector_backend.poc_analyzer import create_local_poc_analyzer
from dokodetector_backend.recording_state_contract import RecordingStateSnapshot

RECORDING = "m4-recording"
SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": RECORDING,
    "relative_path": "data/intake/recordings/m4-recording/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10_000_000,
}
ACTOR = {"kind": "human", "id": "m4-reviewer"}


def _reference(revision, node_id: str) -> dict:
    return {
        "kind": "pipeline-node-revision",
        "resource_id": revision.revision_id,
        "schema_version": "event-data/v1",
        "sha256": revision.content_sha256,
        "node_id": node_id,
        "revision_id": revision.revision_id,
    }


def _snapshot(generated: dict | None = None, completed: dict | None = None) -> dict:
    slots = {
        name: {
            "generated": {
                "state": "empty",
                "resource": None,
                "stale_reason": None,
                "dependencies": [],
            },
            "completed_reference": {
                "state": "empty",
                "resource": None,
                "stale_reason": None,
                "dependencies": [],
            },
        }
        for name in (
            "events",
            "visible_cards",
            "table_plane_calibration",
            "virtual_scenes",
            "visual_identities",
            "table_observations",
            "reconstruction_results",
        )
    }
    for field, ref in (("generated", generated), ("completed_reference", completed)):
        if ref is not None:
            slots["events"][field] = {
                "state": "selected",
                "resource": ref,
                "stale_reason": None,
                "dependencies": [],
            }
    return {
        "schema_version": "recording-state-snapshot/v1",
        "recording_id": RECORDING,
        "snapshot_id": "rs_" + "0" * 64,
        "predecessor_snapshot_id": None,
        "slots": slots,
        "independent_reviews": [],
    }


def _snapshot_payload(generated=None, completed=None, reviews=None, predecessor=None) -> dict:
    value = _snapshot(generated, completed)
    value["predecessor_snapshot_id"] = predecessor
    value["independent_reviews"] = reviews or []
    content = {key: part for key, part in value.items() if key != "snapshot_id"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    value["snapshot_id"] = "rs_" + hashlib.sha256(canonical.encode()).hexdigest()
    return value


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        repository_root=Path(__file__).parents[2],
        evidence_root=tmp_path / "runtime",
        operations_root=tmp_path / "operations",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "packages",
        pending_video_root=tmp_path / "incoming",
        frontend_dist=tmp_path / "frontend",
    )


def test_recording_state_real_api_workflow_survives_restart(tmp_path):
    app = create_app(_settings(tmp_path), analyzer=create_local_poc_analyzer())
    client = TestClient(app)
    edits = app.state.pipeline_node_edits
    node_store = edits.store

    input_content = {
        "schema_version": "event-data/v1",
        "events": [
            {
                "event_id": "event-1",
                "event_type": "card_state_changed",
                "start_us": 100,
                "end_us": 200,
            }
        ],
    }
    input_revision = node_store.create(
        "events-input", "Input events", "events", SOURCE, input_content, {}
    )
    seed = _snapshot_payload(completed=_reference(input_revision, "events-input"))
    response = client.post(f"/api/recordings/{RECORDING}/state", json=seed)
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["head"]["version"] == 1
    assert (
        first["snapshot"]["slots"]["events"]["completed_reference"]["resource"]["revision_id"]
        == input_revision.revision_id
    )

    # Deterministic producer stub uses only the persisted frozen input reference.
    frozen = {
        "recording_id": RECORDING,
        "snapshot_id": first["snapshot"]["snapshot_id"],
        "head_version": first["head"]["version"],
        "inputs": {"events": [_reference(input_revision, "events-input")]},
        "select_output_on_completion": False,
        "expected_head_version": None,
    }
    output_content = {
        "schema_version": "event-data/v1",
        "events": [
            {
                "event_id": "event-1",
                "event_type": "card_state_changed",
                "start_us": 100,
                "end_us": 250,
            }
        ],
    }
    output_revision = node_store.create(
        "events-generated",
        "Generated events",
        "events",
        SOURCE,
        output_content,
        {"frozen_inputs": frozen, "processor": "deterministic-m4"},
    )
    output_ref = _reference(output_revision, "events-generated")
    generated_snapshot = _snapshot_payload(
        generated=output_ref,
        completed=_reference(input_revision, "events-input"),
        predecessor=first["snapshot"]["snapshot_id"],
    )
    store = app.state.recording_state_store
    store.put(RecordingStateSnapshot.model_validate(generated_snapshot))
    second_update = {
        "recording_id": RECORDING,
        "expected_head_version": 1,
        "snapshot_id": generated_snapshot["snapshot_id"],
        "action": "select_snapshot",
    }
    second = client.put(f"/api/recordings/{RECORDING}/state", json=second_update).json()
    assert second["head"]["version"] == 2
    assert second["snapshot"]["slots"]["events"]["generated"]["resource"] == output_ref

    review = client.post(
        "/api/pipeline/nodes/events-generated/reviews/overall",
        json={
            "review_id": "review-m4-a",
            "revision_id": output_revision.revision_id,
            "question": "Are event times correct?",
            "decision": "accepted",
            "reviewer": ACTOR,
            "evidence": {"policy": "m4-fixture/v1", "source": "fixture"},
        },
    )
    assert review.status_code == 200, review.text
    assert review.json()["decision"] == "accepted"
    second_review = client.post(
        "/api/pipeline/nodes/events-generated/reviews/overall",
        json={
            "review_id": "review-m4-b",
            "revision_id": output_revision.revision_id,
            "question": "Are event times correct?",
            "decision": "needs_correction",
            "reviewer": {"kind": "human", "id": "m4-reviewer-2"},
            "evidence": {"policy": "m4-fixture/v1", "source": "fixture-2"},
        },
    )
    assert second_review.status_code == 200, second_review.text
    assert second_review.json()["decision"] == "needs_correction"

    # Accepted downstream use protects generated content; the first edit copies it.
    PipelineNodeUses(node_store).accept(
        "m4-run", [("events-generated", output_revision.revision_id)]
    )
    edited_content = {
        "schema_version": "event-data/v1",
        "events": [
            {
                "event_id": "event-1",
                "event_type": "card_state_changed",
                "start_us": 100,
                "end_us": 300,
            }
        ],
    }
    edited = client.post(
        "/api/pipeline/nodes/events-generated/edit",
        json={
            "expected_revision_id": output_revision.revision_id,
            "idempotency_key": "m4-edit-1",
            "actor": ACTOR,
            "content": edited_content,
        },
    )
    assert edited.status_code == 200, edited.text
    edited_result = edited.json()
    assert edited_result["copied"] is True
    assert edited_result["node_id"] != "events-generated"

    # Keep the generated pointer and independent review while selecting edited work.
    edited_revision = node_store.read_revision(
        edited_result["node_id"], edited_result["revision_id"]
    )
    edited_ref = _reference(edited_revision, edited_result["node_id"])
    third_snapshot = _snapshot_payload(
        generated=output_ref,
        completed=edited_ref,
        reviews=[
            {
                "review_kind": "pipeline-review",
                "review_id": "review-m4-a",
                "resource": output_ref,
                "state": "completed",
            },
            {
                "review_kind": "pipeline-review",
                "review_id": "review-m4-b",
                "resource": output_ref,
                "state": "completed",
            },
        ],
        predecessor=generated_snapshot["snapshot_id"],
    )
    store.put(RecordingStateSnapshot.model_validate(third_snapshot))
    third = client.put(
        f"/api/recordings/{RECORDING}/state",
        json={
            "recording_id": RECORDING,
            "expected_head_version": 2,
            "snapshot_id": third_snapshot["snapshot_id"],
            "action": "select_snapshot",
        },
    ).json()
    assert third["head"]["version"] == 3
    assert third["snapshot"]["slots"]["events"]["generated"]["resource"] == output_ref
    assert third["snapshot"]["slots"]["events"]["completed_reference"]["resource"] == edited_ref
    assert [item["review_id"] for item in third["snapshot"]["independent_reviews"]] == [
        "review-m4-a",
        "review-m4-b",
    ]
    review_list = client.get(
        f"/api/pipeline/nodes/events-generated/revisions/{output_revision.revision_id}/reviews"
    ).json()
    assert {item["review_id"] for item in review_list} == {"review-m4-a", "review-m4-b"}
    assert {item["decision"] for item in review_list} == {"accepted", "needs_correction"}
    assert (
        node_store.read_revision("events-generated", output_revision.revision_id).content
        == output_content
    )
    assert (
        node_store.read_revision(edited_result["node_id"], edited_result["revision_id"]).content
        == edited_content
    )
    assert (
        node_store.read_revision("events-generated", output_revision.revision_id).metadata[
            "frozen_inputs"
        ]
        == frozen
    )

    stale = client.put(
        f"/api/recordings/{RECORDING}/state",
        json={**second_update, "snapshot_id": first["snapshot"]["snapshot_id"]},
    )
    assert stale.status_code == 409
    assert (
        client.get(
            f"/api/recordings/{RECORDING}/state/snapshots/{first['snapshot']['snapshot_id']}"
        ).json()
        == first["snapshot"]
    )

    # The replaced workflow never reads or writes the legacy selection/history roots.
    legacy_selections = node_store.root / ".pipeline-node-selections"
    assert not legacy_selections.exists()

    restarted = TestClient(create_app(_settings(tmp_path), analyzer=create_local_poc_analyzer()))
    current = restarted.get(f"/api/recordings/{RECORDING}/state").json()
    assert current["head"]["version"] == 3
    assert current["snapshot"] == third_snapshot
    assert (
        restarted.get(
            f"/api/recordings/{RECORDING}/state/snapshots/{generated_snapshot['snapshot_id']}"
        ).json()
        == generated_snapshot
    )
    assert (
        restarted.get(
            f"/api/pipeline/nodes/{edited_result['node_id']}/revisions/{edited_result['revision_id']}"
        ).json()["content"]
        == edited_content
    )
