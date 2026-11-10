"""M4 real-API proof for recording-owned current state."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dokodetector_backend import pipeline_node_transactions
from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.pipeline_node_uses import PipelineNodeUses
from dokodetector_backend.poc_analyzer import create_local_poc_analyzer
from dokodetector_backend.recording_state_contract import (
    RecordingStateSnapshot,
    SnapshotFrozenProcessorInputs,
)

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


def _import_fixture_recording(app, client, recording_id: str, tmp_path: Path) -> None:
    import test_round_analysis_api as fixtures
    from test_training_recordings import bundle_parts

    previous = fixtures.RECORDING_ID
    try:
        fixtures.RECORDING_ID = recording_id
        fixtures._write_recording_bundle(app)
    finally:
        fixtures.RECORDING_ID = previous
    staging = tmp_path / f"upload-{recording_id}"
    shutil.move(app.state.repository_bundle_storage.bundle_path(recording_id), staging)
    proposal = next((staging / "predictions").glob("*.json"))
    video = next((staging / "videos").glob("*.mov"))
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:r=2",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(video),
        ],
        check=True,
    )
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    source_path = staging / "source-record.json"
    source = json.loads(source_path.read_text())
    source.update(sha256=digest, byte_length=video.stat().st_size)
    source_path.write_text(json.dumps(source, separators=(",", ":")))
    proposal_data = json.loads(proposal.read_text())
    proposal_data["source_sha256"] = digest
    proposal.write_text(json.dumps(proposal_data, separators=(",", ":")))
    manifest_path = staging / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["source_sha256"] = digest
    for descriptor, path in (
        (manifest["files"]["video"], video),
        (manifest["files"]["source_record"], source_path),
        (manifest["files"]["proposal_generator_runs"][0], proposal),
    ):
        raw = path.read_bytes()
        descriptor.update(byte_length=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    manifest_path.write_text(json.dumps(manifest, separators=(",", ":")))
    fixture = {
        "manifest": (staging / "manifest.json").read_bytes(),
        "source_record": (staging / "source-record.json").read_bytes(),
        "task_enrollment": (staging / "initial-task-enrollment.json").read_bytes(),
        "proposal": proposal.read_bytes(),
        "proposal_name": proposal.name,
        "video": video.read_bytes(),
        "video_name": video.name,
    }
    response = client.put(f"/v1/repository-bundles/{recording_id}", files=bundle_parts(fixture))
    assert response.status_code == 201, response.text


def _produce_events_from_frozen_inputs(frozen, node_store, state_store, output_node_id):
    """Deterministic test adapter that resolves and validates the frozen exact input."""

    request = SnapshotFrozenProcessorInputs.model_validate(frozen)
    snapshot = state_store.get(request.recording_id, request.snapshot_id).snapshot
    if snapshot.recording_id != request.recording_id:
        raise ValueError("frozen snapshot belongs to another recording")
    selected = snapshot.slots["events"].completed_reference
    frozen_refs = request.inputs.get("events", [])
    if selected.resource is None or frozen_refs != [selected.resource]:
        raise ValueError("frozen event input does not match its source snapshot")
    resource = frozen_refs[0]
    if resource.kind != "pipeline-node-revision" or resource.node_id is None:
        raise ValueError("deterministic event adapter requires a node revision")
    node = node_store.get(resource.node_id)
    if node.source.get("recording_id") != request.recording_id or node.content_type != "events":
        raise ValueError("frozen event resource belongs to another recording or content type")
    revision = node_store.read_authorized_revision(resource.node_id, resource.revision_id)
    if (
        revision.content_sha256 != resource.sha256
        or revision.revision_id != resource.resource_id
        or revision.content.get("schema_version") != resource.schema_version
    ):
        raise ValueError("frozen event resource identity or digest mismatch")
    content = json.loads(json.dumps(revision.content))
    for event in content["events"]:
        event["end_us"] += 50
    return node_store.create(
        output_node_id,
        "Generated events",
        "events",
        node.source,
        content,
        {
            "frozen_inputs": request.model_dump(mode="json"),
            "processor": "deterministic-m4",
        },
    )


def _disable_legacy_discovery(app, monkeypatch):
    """Fail if this workflow invokes old selection, history, or workspace discovery."""

    def forbidden(*_args, **_kwargs):
        raise AssertionError("legacy selection/history discovery was called")

    node_store = app.state.pipeline_node_edits.store
    selection_store = app.state.pipeline_selection_store
    workspace_service = app.state.pipeline_workspace_service
    monkeypatch.setattr(node_store, "history", forbidden)
    monkeypatch.setattr(node_store, "list_nodes", forbidden)
    monkeypatch.setattr(node_store, "find_revision", forbidden)
    monkeypatch.setattr(node_store, "read_published_revision", forbidden)
    monkeypatch.setattr(selection_store, "get_exact", forbidden)
    monkeypatch.setattr(selection_store, "update_exact", forbidden)
    monkeypatch.setattr(workspace_service, "get_workspace", forbidden)
    monkeypatch.setattr(workspace_service, "get_statuses", forbidden)
    journal_reads = []
    read_json = pipeline_node_transactions._read_json

    def track_journal_reads(path):
        path = Path(path)
        if path.parent == node_store.root / ".coordinated-transactions":
            journal_reads.append(path)
        return read_json(path)

    monkeypatch.setattr(pipeline_node_transactions, "_read_json", track_journal_reads)
    transaction_root = node_store.root / ".coordinated-transactions"
    transaction_root.mkdir(parents=True, exist_ok=True)
    for index in range(25):
        (transaction_root / f"committed-{index:03}.json").write_text("{}")
    return journal_reads


def test_empty_head_does_not_prove_absence_of_unselected_events(tmp_path):
    app = create_app(_settings(tmp_path), analyzer=create_local_poc_analyzer())
    with TestClient(app) as client:
        response = client.post(f"/api/recordings/{RECORDING}/state", json=_snapshot_payload())
        assert response.status_code == 200, response.text
        before = app.state.recording_state_store.get_current(RECORDING)
        workspace = app.state.pipeline_workspace_service
        assert (
            workspace.get_statuses([RECORDING], analyses_by_recording={})[RECORDING]["stages"][0][
                "state"
            ]
            == "video-only"
        )

        app.state.pipeline_node_edits.store.create(
            "unselected-events",
            "Unselected events",
            "events",
            SOURCE,
            {"schema_version": "event-data/v1", "events": []},
            {},
        )

        assert app.state.recording_state_store.get_current(RECORDING) == before
        assert (
            workspace.get_statuses([RECORDING], analyses_by_recording={})[RECORDING]["stages"][0][
                "state"
            ]
            == "data-available"
        )


def test_head_proof_list_uses_persisted_state_without_node_discovery(tmp_path, monkeypatch):
    settings = _settings(tmp_path).model_copy(update={"recording_list_head_proof": True})
    app = create_app(settings, analyzer=create_local_poc_analyzer())
    node_store = app.state.pipeline_node_edits.store
    content = {
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
    with TestClient(app) as client:
        _import_fixture_recording(app, client, RECORDING, tmp_path)
        _import_fixture_recording(app, client, "missing-head", tmp_path)
        stored = app.state.recording_bundle_store.get_metadata(RECORDING)
        source = dict(
            SOURCE,
            video_sha256=stored.source_sha256,
            byte_length=stored.video_byte_length,
            duration_us=1_000_000,
        )
        revision = node_store.create("events-proof", "Events", "events", source, content, {})
        initial = client.post(
            f"/api/recordings/{RECORDING}/state",
            json=_snapshot_payload(generated=_reference(revision, "events-proof")),
        )
        assert initial.status_code == 200, initial.text
        noop = client.put(
            f"/api/recordings/{RECORDING}/state/events/working-content",
            json={
                "expected_head_version": 1,
                "idempotency_key": "proof-noop",
                "actor": ACTOR,
                "content": content,
            },
        )
        assert noop.status_code == 200, noop.text
        assert noop.json()["edit"]["reason"] == "no_change"
        assert noop.json()["head"]["version"] == 2
        edited = dict(content, events=[dict(content["events"][0], end_us=250)])
        response = client.put(
            f"/api/recordings/{RECORDING}/state/events/working-content",
            json={
                "expected_head_version": 2,
                "idempotency_key": "proof-edit",
                "actor": ACTOR,
                "content": edited,
            },
        )
        assert response.status_code == 200, response.text
        stale = client.put(
            f"/api/recordings/{RECORDING}/state/events/working-content",
            json={
                "expected_head_version": 2,
                "idempotency_key": "proof-stale",
                "actor": ACTOR,
                "content": edited,
            },
        )
        assert stale.status_code == 409

        stale_snapshot = response.json()["snapshot"]
        stale_snapshot["predecessor_snapshot_id"] = stale_snapshot["snapshot_id"]
        stale_snapshot["slots"]["events"]["generated"]["state"] = "stale"
        stale_snapshot["slots"]["events"]["generated"]["stale_reason"] = "manual_invalidation"
        canonical = json.dumps(
            {key: value for key, value in stale_snapshot.items() if key != "snapshot_id"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        stale_snapshot["snapshot_id"] = "rs_" + hashlib.sha256(canonical.encode()).hexdigest()
        app.state.recording_state_store.put(RecordingStateSnapshot.model_validate(stale_snapshot))
        update = client.put(
            f"/api/recordings/{RECORDING}/state",
            json={
                "recording_id": RECORDING,
                "expected_head_version": 3,
                "snapshot_id": stale_snapshot["snapshot_id"],
                "action": "select_snapshot",
            },
        )
        assert update.status_code == 200, update.text

        def forbidden(*_args, **_kwargs):
            raise AssertionError("list called legacy node discovery")

        monkeypatch.setattr(
            app.state.pipeline_workspace_service, "_node_revisions_for_recordings", forbidden
        )
        response = client.get("/v1/recordings")
        assert response.status_code == 200, response.text
        rows = {row["recording_id"]: row for row in response.json()["recordings"]}
        assert rows[RECORDING]["pipeline_status"]["stages"][0]["state"] == "data-available"
        assert rows[RECORDING]["can_start_analysis"] is False
        assert rows[RECORDING]["analysis_blocker"]
        assert all(
            stage["state"] == "unavailable"
            for stage in rows["missing-head"]["pipeline_status"]["stages"]
        )
        empty_snapshot = _snapshot_payload()
        empty_snapshot["recording_id"] = "missing-head"
        canonical = json.dumps(
            {key: value for key, value in empty_snapshot.items() if key != "snapshot_id"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        empty_snapshot["snapshot_id"] = "rs_" + hashlib.sha256(canonical.encode()).hexdigest()
        assert (
            client.post("/api/recordings/missing-head/state", json=empty_snapshot).status_code
            == 200
        )
        empty_row = next(
            row
            for row in client.get("/v1/recordings").json()["recordings"]
            if row["recording_id"] == "missing-head"
        )
        assert [stage["state"] for stage in empty_row["pipeline_status"]["stages"]] == [
            "unavailable",
            "unavailable",
            "unavailable",
            "unavailable",
            "empty",
        ]
        current = app.state.recording_state_store.get_current(RECORDING)
        head_path = app.state.recording_state_store.head_path(RECORDING)
        head_bytes = head_path.read_bytes()
        snapshot_path = (
            app.state.recording_state_store.snapshot_path(RECORDING, current.head.snapshot_id)
            / "snapshot.json"
        )
        snapshot_bytes = snapshot_path.read_bytes()
        for path in (head_path, snapshot_path):
            path.write_text("invalid")
            broken = client.get("/v1/recordings")
            assert broken.status_code == 200
            row = next(
                row for row in broken.json()["recordings"] if row["recording_id"] == RECORDING
            )
            assert all(
                stage["state"] == "unavailable" for stage in row["pipeline_status"]["stages"]
            )
            path.write_bytes(head_bytes if path == head_path else snapshot_bytes)
        snapshot_path.unlink()
        missing_snapshot = client.get("/v1/recordings")
        assert missing_snapshot.status_code == 200
        row = next(
            row for row in missing_snapshot.json()["recordings"] if row["recording_id"] == RECORDING
        )
        assert row["pipeline_status"]["stages"][0]["state"] == "unavailable"
        snapshot_path.write_bytes(snapshot_bytes)

        # History and selected content are validated by the operation that opens them.
        old_path = node_store.revision_path("events-proof", revision.revision_id) / "revision.json"
        old_path.write_text("invalid")
        selected = current.snapshot.slots["events"].generated.resource
        selected_path = (
            node_store.revision_path(selected.node_id, selected.revision_id) / "revision.json"
        )
        selected_path.write_text("invalid")
        assert client.get("/v1/recordings").json()["recordings"]
        with pytest.raises((ValueError, KeyError)):
            node_store.read_authorized_revision(selected.node_id, selected.revision_id)

    restarted = create_app(settings, analyzer=create_local_poc_analyzer())
    with TestClient(restarted) as client:
        rows = {
            row["recording_id"]: row for row in client.get("/v1/recordings").json()["recordings"]
        }
        assert rows[RECORDING]["pipeline_status"]["stages"][0]["state"] == "data-available"
        assert rows["missing-head"]["pipeline_status"]["stages"][0]["state"] == "unavailable"


def test_recording_state_real_api_workflow_survives_restart(tmp_path, monkeypatch):
    app = create_app(_settings(tmp_path), analyzer=create_local_poc_analyzer())
    journal_reads = _disable_legacy_discovery(app, monkeypatch)
    client = TestClient(app)
    assert client.get(f"/api/recordings/{RECORDING}/state/history/snapshots").status_code == 404
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

    # Freeze one exact input before current selection moves to a different event revision.
    frozen = {
        "recording_id": RECORDING,
        "snapshot_id": first["snapshot"]["snapshot_id"],
        "head_version": first["head"]["version"],
        "inputs": {"events": [_reference(input_revision, "events-input")]},
        "select_output_on_completion": False,
        "expected_head_version": None,
    }
    decoy_content = {
        "schema_version": "event-data/v1",
        "events": [
            {
                "event_id": "decoy-event",
                "event_type": "card_state_changed",
                "start_us": 800,
                "end_us": 900,
            }
        ],
    }
    decoy_revision = node_store.create(
        "events-decoy", "Decoy events", "events", SOURCE, decoy_content, {}
    )
    decoy_snapshot = _snapshot_payload(
        completed=_reference(decoy_revision, "events-decoy"),
        predecessor=first["snapshot"]["snapshot_id"],
    )
    store = app.state.recording_state_store
    store.put(RecordingStateSnapshot.model_validate(decoy_snapshot))
    moved = client.put(
        f"/api/recordings/{RECORDING}/state",
        json={
            "recording_id": RECORDING,
            "expected_head_version": 1,
            "snapshot_id": decoy_snapshot["snapshot_id"],
            "action": "select_snapshot",
        },
    ).json()
    assert moved["head"]["version"] == 2

    bad_frozen = dict(frozen)
    bad_ref = dict(frozen["inputs"]["events"][0])
    bad_ref["sha256"] = "b" * 64
    bad_frozen["inputs"] = {"events": [bad_ref]}
    with pytest.raises(ValueError, match="does not match its source snapshot"):
        _produce_events_from_frozen_inputs(
            bad_frozen, node_store, store, "events-generated-bad-input"
        )
    assert not node_store._node_path("events-generated-bad-input").exists()

    corrupt_snapshot = _snapshot_payload(completed=bad_ref)
    store.put(RecordingStateSnapshot.model_validate(corrupt_snapshot))
    corrupt_frozen = {
        **frozen,
        "snapshot_id": corrupt_snapshot["snapshot_id"],
        "inputs": {"events": [bad_ref]},
    }
    with pytest.raises(ValueError, match="identity or digest mismatch"):
        _produce_events_from_frozen_inputs(
            corrupt_frozen, node_store, store, "events-generated-corrupt-input"
        )
    assert not node_store._node_path("events-generated-corrupt-input").exists()

    output_revision = _produce_events_from_frozen_inputs(
        frozen, node_store, store, "events-generated"
    )
    output_content = json.loads(json.dumps(input_content))
    output_content["events"][0]["end_us"] += 50
    output_ref = _reference(output_revision, "events-generated")
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

    generated_snapshot = _snapshot_payload(
        generated=output_ref,
        completed=_reference(decoy_revision, "events-decoy"),
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
        predecessor=decoy_snapshot["snapshot_id"],
    )
    store.put(RecordingStateSnapshot.model_validate(generated_snapshot))
    second_update = {
        "recording_id": RECORDING,
        "expected_head_version": 2,
        "snapshot_id": generated_snapshot["snapshot_id"],
        "action": "select_snapshot",
    }
    second = client.put(f"/api/recordings/{RECORDING}/state", json=second_update).json()
    assert second["head"]["version"] == 3
    assert second["snapshot"]["slots"]["events"]["generated"]["resource"] == output_ref

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
    edited = client.put(
        f"/api/recordings/{RECORDING}/state/events/working-content",
        json={
            "expected_head_version": 3,
            "idempotency_key": "m4-edit-1",
            "actor": ACTOR,
            "content": edited_content,
        },
    )
    assert edited.status_code == 200, edited.text
    edit_response = edited.json()
    edited_result = edit_response["edit"]
    assert edited_result["copied"] is True
    assert edited_result["node_id"] != "events-generated"

    # The selected working adapter updates generated state and leaves the reference and reviews.
    third = edit_response
    third_snapshot = third["snapshot"]
    edited_ref = third_snapshot["slots"]["events"]["generated"]["resource"]
    assert third["head"]["version"] == 4
    assert edited_ref["node_id"] == edited_result["node_id"]
    assert third_snapshot["slots"]["events"]["completed_reference"]["resource"] == (
        _reference(decoy_revision, "events-decoy")
    )
    assert [item["review_id"] for item in third_snapshot["independent_reviews"]] == [
        "review-m4-a",
        "review-m4-b",
    ]
    assert all(item["resource"] == output_ref for item in third_snapshot["independent_reviews"])
    review_list = client.get(
        f"/api/pipeline/nodes/events-generated/revisions/{output_revision.revision_id}/reviews"
    ).json()
    assert {item["review_id"] for item in review_list} == {"review-m4-a", "review-m4-b"}
    assert {item["decision"] for item in review_list} == {"accepted", "needs_correction"}
    assert (
        node_store.read_authorized_revision("events-generated", output_revision.revision_id).content
        == output_content
    )
    assert (
        node_store.read_authorized_revision(
            edited_result["node_id"], edited_result["revision_id"]
        ).content
        == edited_content
    )
    assert (
        node_store.read_authorized_revision(
            "events-generated", output_revision.revision_id
        ).metadata["frozen_inputs"]
        == frozen
    )
    assert journal_reads == []

    stale = client.put(
        f"/api/recordings/{RECORDING}/state",
        json={**second_update, "snapshot_id": first["snapshot"]["snapshot_id"]},
    )
    assert stale.status_code == 409
    cross_recording = client.put(
        "/api/recordings/another-recording/state",
        json={
            "recording_id": RECORDING,
            "expected_head_version": 4,
            "snapshot_id": third_snapshot["snapshot_id"],
            "action": "select_snapshot",
        },
    )
    assert cross_recording.status_code == 409
    assert client.get(f"/api/recordings/{RECORDING}/state").json()["head"]["version"] == 4
    assert (
        client.get(
            f"/api/recordings/{RECORDING}/state/snapshots/{first['snapshot']['snapshot_id']}"
        ).json()
        == first["snapshot"]
    )

    # The replaced workflow never reads or writes the legacy selection/history roots.
    legacy_selections = node_store.root / ".pipeline-node-selections"
    assert not legacy_selections.exists()

    restarted_app = create_app(_settings(tmp_path), analyzer=create_local_poc_analyzer())
    restarted_journal_reads = _disable_legacy_discovery(restarted_app, monkeypatch)
    restarted = TestClient(restarted_app)
    current = restarted.get(f"/api/recordings/{RECORDING}/state").json()
    assert current["head"]["version"] == 4
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
    assert restarted_journal_reads == []
