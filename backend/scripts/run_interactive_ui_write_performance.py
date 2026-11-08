#!/usr/bin/env python3
"""Retain preliminary samples for durable interactive writes and controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/tests"))
NODE_SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "m7-recording",
    "relative_path": "data/intake/recordings/m7-recording/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10_000_000,
}
NODE_CONTENT = {
    "schema_version": "event-data/v1",
    "events": [
        {"event_id": "e", "event_type": "card_state_changed", "start_us": 100, "end_us": 200}
    ],
}
ACTOR = {"kind": "human", "id": "m7-operator"}


def _settings(root: Path) -> Any:
    from dokodetector_backend.config import Settings

    return Settings(
        _env_file=None,
        repository_root=ROOT,
        evidence_root=root / "runtime",
        operations_root=root / "operations",
        frontend_dist=root / "frontend",
        repository_intake_root=root / "recordings",
        evidence_package_intake_root=root / "packages",
        pending_video_root=root / "pending",
    )


def _sample(
    client: TestClient, name: str, method: str, path: str, **kwargs: Any
) -> tuple[dict[str, Any], Any]:
    started = time.perf_counter_ns()
    response = client.request(method, path, **kwargs)
    body = response.content
    result = {
        "case": name,
        "method": method,
        "path": path,
        "duration_ns": time.perf_counter_ns() - started,
        "status_code": response.status_code,
        "response_bytes": len(body),
        "response_sha256": hashlib.sha256(body).hexdigest(),
        "ok": True,
        "error": None,
    }
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if response.status_code >= 400:
        result["response_error"] = payload
    return result, payload


def run() -> dict[str, Any]:
    from support.job_participants import FakeParticipant

    from dokodetector_backend.app import create_app
    from dokodetector_backend.poc_analyzer import create_local_poc_analyzer

    samples: list[dict[str, Any]] = []
    effects: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="doko-ui-m7-writes-") as temporary:
        root = Path(temporary).resolve()
        app = create_app(_settings(root), analyzer=create_local_poc_analyzer())
        app.state.job_type_registry.register_fake(FakeParticipant(root / "operations/job-domain"))
        with TestClient(app) as client:
            _measure_node_writes(app, client, samples, effects)
            _measure_selection_writes(client, samples, effects)

            def enqueue(label: str) -> dict[str, Any]:
                sample, payload = _sample(
                    client,
                    f"submit_{label}",
                    "POST",
                    "/api/jobs",
                    headers={"Idempotency-Key": str(uuid4())},
                    json={
                        "type": "fake",
                        "context": {"recording_id": "m7-recording"},
                        "request": {"input": label},
                    },
                )
                if sample["status_code"] != 202 or not isinstance(payload, dict):
                    sample.update(ok=False, error="job submission did not return 202 JSON")
                    samples.append(sample)
                    raise RuntimeError(sample["error"])
                samples.append(sample)
                return payload

            first = enqueue("first")
            second = enqueue("second")
            page_sample, page = _sample(client, "queue_read_before_move", "GET", "/api/jobs")
            samples.append(page_sample)
            revision = page["queue_revision"]
            move_sample, moved = _sample(
                client,
                "queue_move",
                "POST",
                "/api/jobs/queue/move",
                json={
                    "group_id": first["id"],
                    "before_group_id": None,
                    "expected_revision": revision,
                },
            )
            if move_sample["status_code"] != 200 or moved["revision"] != revision + 1:
                move_sample.update(ok=False, error="queue move did not persist one revision")
            samples.append(move_sample)
            after_move_sample, after_move = _sample(
                client, "queue_read_after_move", "GET", "/api/jobs?scope=active"
            )
            if after_move["groups"] != moved["groups"]:
                after_move_sample.update(ok=False, error="queue order did not persist the move")
            samples.append(after_move_sample)

            cancel_sample, cancelled = _sample(
                client, "cancel_queued_job", "POST", f"/api/jobs/{second['id']}/cancel", json={}
            )
            if cancel_sample["status_code"] != 200 or cancelled["state"] != "cancelled":
                cancel_sample.update(ok=False, error="cancel state was not durable")
            samples.append(cancel_sample)
            retry_sample, retried = _sample(
                client,
                "retry_cancelled_job",
                "POST",
                f"/api/jobs/{second['id']}/retry",
                headers={"Idempotency-Key": str(uuid4())},
                json={},
            )
            if retry_sample["status_code"] != 202 or retried["retry_of"] != second["id"]:
                retry_sample.update(ok=False, error="retry lineage was not preserved")
            samples.append(retry_sample)
            detail_sample, detail = _sample(
                client, "retry_detail_after_write", "GET", f"/api/jobs/{retried['id']}"
            )
            if detail_sample["status_code"] != 200 or detail["retry_of"] != second["id"]:
                detail_sample.update(ok=False, error="retry lineage did not survive readback")
            samples.append(detail_sample)
            effects.extend(
                [
                    {
                        "effect": "queue_revision_increment",
                        "expected": revision + 1,
                        "actual": moved["revision"],
                    },
                    {
                        "effect": "cancel_state",
                        "expected": "cancelled",
                        "actual": cancelled["state"],
                    },
                    {
                        "effect": "retry_parent",
                        "expected": second["id"],
                        "actual": retried["retry_of"],
                    },
                ]
            )

            queue_sample, frame_page = _sample(
                client, "frame_review_queue", "GET", "/api/frame-reviews/0096-M4?limit=1"
            )
            samples.append(queue_sample)
            frame_item = frame_page["items"][0]
            frame_route = (
                f"/api/frame-reviews/0096-M4/items/{frame_item['recording_id']}/"
                f"{frame_item['item_id']}/workflow"
            )
            workflow_sample, workflow = _sample(
                client,
                "frame_review_defer",
                "PUT",
                frame_route,
                json={"queue_digest": frame_page["queue_digest"], "action": "defer"},
            )
            if workflow_sample["status_code"] != 200 or workflow["deferred"] is not True:
                workflow_sample.update(ok=False, error="frame review workflow edit failed")
            samples.append(workflow_sample)
            reread_sample, _ = _sample(
                client, "frame_review_read_after_save", "GET", "/api/frame-reviews/0096-M4?limit=1"
            )
            workflow_state = app.state.frame_review_workflow_store.read(
                "0096-M4", frame_page["queue_digest"]
            )
            expected_item_key = json.dumps(
                [frame_item["recording_id"], frame_item["item_id"]], separators=(",", ":")
            )
            if expected_item_key not in workflow_state["deferred_item_keys"]:
                reread_sample.update(ok=False, error="frame review edit was not durable")
            samples.append(reread_sample)
            effects.append(
                {
                    "effect": "frame_review_deferred_item",
                    "expected": frame_item["item_id"],
                    "actual": frame_item["item_id"]
                    if expected_item_key in workflow_state["deferred_item_keys"]
                    else None,
                }
            )

            # M0 records this browser URL, but OpenAPI and the web source contain no matching
            # backend route/request constructor. Measure the observable route boundary without
            # inventing an API contract.
            gap_sample, gap_payload = _sample(
                client,
                "unregistered_ui_video_url",
                "GET",
                "/api/recordings/m7-unregistered-video/video",
            )
            if gap_sample["status_code"] != 404 or not isinstance(gap_payload, dict):
                gap_sample.update(
                    ok=False, error="unregistered UI URL did not return the expected 404"
                )
            samples.append(gap_sample)
        _measure_calibration_writes(root / "calibration", samples, effects)
        _measure_pipeline_run_submission(root / "pipeline-run", samples, effects)
    return {
        "schema_version": "0114-m7-write-samples/v1",
        "measurement": "one synchronous ASGI HTTP response per named case; preliminary only",
        "fixture": "temporary storage; fake job participant, real job and queue persistence",
        "controlled_load": None,
        "samples": samples,
        "durable_effects": effects,
        "all_pass": all(sample["ok"] for sample in samples),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"{'PASS' if result['all_pass'] else 'FAIL'}: {len(result['samples'])} M7 write samples")
    return 0 if result["all_pass"] else 1


def _measure_node_writes(
    app: Any,
    client: TestClient,
    samples: list[dict[str, Any]],
    effects: list[dict[str, Any]],
) -> None:
    store = app.state.pipeline_node_edits.store
    base = store.create("m7-node", "M7 event node", "events", NODE_SOURCE, NODE_CONTENT, {})
    changed_content = {
        "schema_version": "event-data/v1",
        "events": [
            {"event_id": "e", "event_type": "card_state_changed", "start_us": 100, "end_us": 300}
        ],
    }
    edited_sample, edited = _sample(
        client,
        "pipeline_node_edit",
        "POST",
        "/api/pipeline/nodes/m7-node/edit",
        json={
            "expected_revision_id": base.revision_id,
            "idempotency_key": "m7-edit",
            "actor": ACTOR,
            "pointers": {"e": "/events/0"},
            "base_pointers": {"e": "/events/0"},
            "operations": [{"kind": "replace", "before": ["e"], "after": ["e"]}],
            "content": changed_content,
        },
    )
    if edited_sample["status_code"] != 200 or not edited.get("revision_id"):
        edited_sample.update(ok=False, error="pipeline node edit was not accepted")
    samples.append(edited_sample)
    edit_read_sample, edit_read = _sample(
        client,
        "pipeline_node_edit_readback",
        "GET",
        f"/api/pipeline/nodes/m7-node/revisions/{edited.get('revision_id', 'missing')}",
    )
    if edit_read_sample["status_code"] != 200 or edit_read.get("content") != changed_content:
        edit_read_sample.update(ok=False, error="edited node content did not persist exactly")
    samples.append(edit_read_sample)
    effects.append(
        {
            "effect": "pipeline_node_edit_content",
            "expected": changed_content,
            "actual": edit_read.get("content"),
        }
    )

    copy_sample, copied = _sample(
        client,
        "pipeline_node_copy",
        "POST",
        "/api/pipeline/nodes/m7-node/copy",
        json={
            "revision_id": edited["revision_id"],
            "idempotency_key": "m7-copy",
            "actor": ACTOR,
            "reason": "user_requested_copy",
        },
    )
    if copy_sample["status_code"] != 200 or copied.get("revision_id") == edited["revision_id"]:
        copy_sample.update(ok=False, error="copy did not create a distinct immutable revision")
    samples.append(copy_sample)
    copy_read_sample, copy_read = _sample(
        client,
        "pipeline_node_copy_readback",
        "GET",
        "/api/pipeline/nodes/"
        f"{copied.get('node_id', 'missing')}/revisions/"
        f"{copied.get('revision_id', 'missing')}",
    )
    if copy_read_sample["status_code"] != 200 or copy_read.get("content") != changed_content:
        copy_read_sample.update(ok=False, error="copied node content did not persist exactly")
    samples.append(copy_read_sample)

    restore_sample, restored = _sample(
        client,
        "pipeline_node_restore",
        "POST",
        "/api/pipeline/nodes/m7-node/restore",
        json={
            "expected_revision_id": edited["revision_id"],
            "historical_revision_id": base.revision_id,
            "idempotency_key": "m7-restore",
            "actor": ACTOR,
            "pointers": {"e": "/events/0"},
            "base_pointers": {"e": "/events/0"},
            "operations": [{"kind": "replace", "before": ["e"], "after": ["e"]}],
        },
    )
    if restore_sample["status_code"] != 200 or not restored.get("revision_id"):
        restore_sample.update(ok=False, error="historical revision restore was not accepted")
    samples.append(restore_sample)
    if not restored.get("revision_id"):
        raise RuntimeError(f"pipeline restore fixture rejected: {restored}")
    restore_read_sample, restore_read = _sample(
        client,
        "pipeline_node_restore_readback",
        "GET",
        f"/api/pipeline/nodes/m7-node/revisions/{restored.get('revision_id', 'missing')}",
    )
    if restore_read_sample["status_code"] != 200 or restore_read.get("content") != NODE_CONTENT:
        restore_read_sample.update(ok=False, error="restored content or lineage is incorrect")
    samples.append(restore_read_sample)
    effects.append(
        {
            "effect": "pipeline_node_restore_content",
            "expected": NODE_CONTENT,
            "actual": restore_read.get("content"),
        }
    )

    review_requests = (
        (
            "pipeline_item_review",
            "/reviews/item",
            {
                "review_id": "m7-item-review",
                "revision_id": restored["revision_id"],
                "item_id": "e",
                "question": "Is the event correct?",
                "decision": "accepted",
                "reviewer": ACTOR,
                "evidence": {"policy": "pipeline-event-review/v1", "duration_us": 10_000_000},
            },
        ),
        (
            "pipeline_coverage_review",
            "/reviews/coverage",
            {
                "review_id": "m7-coverage-review",
                "revision_id": restored["revision_id"],
                "question": "Was the full recording inspected?",
                "coverage": {
                    "kind": "full_recording",
                    "intervals": [{"start_us": 0, "end_us": 10_000_000}],
                },
                "reviewer": ACTOR,
                "evidence": {"policy": "pipeline-event-review/v1", "duration_us": 10_000_000},
            },
        ),
        (
            "pipeline_overall_review",
            "/reviews/overall",
            {
                "review_id": "m7-overall-review",
                "revision_id": restored["revision_id"],
                "question": "Is this event data set complete and correct?",
                "decision": "accepted",
                "reviewer": ACTOR,
                "evidence": {"policy": "pipeline-event-review/v1", "duration_us": 10_000_000},
            },
        ),
    )
    for name, suffix, body in review_requests:
        sample, payload = _sample(
            client, name, "POST", f"/api/pipeline/nodes/m7-node{suffix}", json=body
        )
        if sample["status_code"] != 200 or payload.get("review_id") != body["review_id"]:
            sample.update(ok=False, error="review write identity mismatch")
        samples.append(sample)
    list_sample, reviews = _sample(
        client,
        "pipeline_review_readback",
        "GET",
        f"/api/pipeline/nodes/m7-node/revisions/{restored['revision_id']}/reviews",
    )
    kinds = {review["kind"] for review in reviews} if isinstance(reviews, list) else set()
    if list_sample["status_code"] != 200 or kinds != {"item", "coverage", "overall"}:
        list_sample.update(ok=False, error="review content did not persist for exact revision")
    samples.append(list_sample)
    effects.append(
        {
            "effect": "pipeline_review_kinds",
            "expected": ["coverage", "item", "overall"],
            "actual": sorted(kinds),
        }
    )


def _measure_selection_writes(
    client: TestClient,
    samples: list[dict[str, Any]],
    effects: list[dict[str, Any]],
) -> None:
    recording_id = "m7-selection-recording"
    stages = (
        ("events", "events"),
        ("observations", "observations"),
        ("visible-cards", "visible-cards"),
        ("visual-identities", "visual-identities"),
    )
    for name, path_part in stages:
        base = f"/api/recordings/{recording_id}/pipeline/{path_part}/selection"
        sample, response = _sample(
            client,
            f"{name}_selection_clear",
            "PUT",
            base,
            json={"expected_revision": 0, "selected_generated": None},
        )
        selection = response.get("selection") if isinstance(response, dict) else None
        if sample["status_code"] != 200 or selection is None or selection["revision"] != 1:
            sample.update(ok=False, error="selection write did not persist revision one")
        samples.append(sample)
        read_sample, readback = _sample(client, f"{name}_selection_readback", "GET", base)
        actual = readback.get("selection") if isinstance(readback, dict) else None
        if read_sample["status_code"] != 200 or actual != selection:
            read_sample.update(ok=False, error="selection readback differs from durable write")
        samples.append(read_sample)
        effects.append(
            {
                "effect": f"{name}_selection_revision",
                "expected": 1,
                "actual": None if actual is None else actual.get("revision"),
            }
        )


def _measure_calibration_writes(
    root: Path,
    samples: list[dict[str, Any]],
    effects: list[dict[str, Any]],
) -> None:
    from run_interactive_ui_pipeline_read_performance import (
        CALIBRATION_PROPOSAL_REVISION,
        CALIBRATION_RECORDING,
        DEFAULT_CACHE,
        DRAFT_ID,
        _link_hard_snapshot,
        _prepare_current_calibration_draft_fixture,
    )
    from table_evidence_analyzer import AnchorCommand

    from dokodetector_backend.app import create_app
    from dokodetector_backend.config import Settings
    from dokodetector_backend.poc_analyzer import create_local_poc_analyzer

    root.mkdir(parents=True)
    _link_hard_snapshot(root, DEFAULT_CACHE)
    _prepare_current_calibration_draft_fixture(root)
    settings = Settings(
        _env_file=None,
        repository_root=root,
        evidence_root=root / ".runtime",
        operations_root=root / "data/operations",
        frontend_dist=root / "frontend",
        repository_intake_root=root / "data/intake/recordings",
        evidence_package_intake_root=root / "data/intake/evidence-packages",
        pending_video_root=root / "data/incoming/videos",
        bonjour_enabled=False,
    )
    app = create_app(settings, analyzer=create_local_poc_analyzer())
    path = f"/api/recordings/{CALIBRATION_RECORDING}/pipeline/calibration-refinement"
    with TestClient(app) as client:
        start_sample, started = _sample(
            client,
            "calibration_draft_start",
            "POST",
            path,
            json={"proposal_revision_id": CALIBRATION_PROPOSAL_REVISION, "draft_id": DRAFT_ID},
        )
        draft = started.get("draft", {}) if isinstance(started, dict) else {}
        if (
            start_sample["status_code"] != 201
            or draft.get("draft_id") != DRAFT_ID
            or started.get("proposal_revision_id") != CALIBRATION_PROPOSAL_REVISION
        ):
            start_sample.update(ok=False, error="calibration draft identity mismatch")
            samples.append(start_sample)
            raise RuntimeError(f"calibration start fixture rejected: {started}")
        samples.append(start_sample)
        from table_evidence_analyzer import CalibrationDraft

        app.state.calibration_refinement_service.store.publish_initial(
            CalibrationDraft.from_mapping(started["draft"])
        )
        initial_revision = draft["revision"]
        initial_commands = draft.get("commands", [])
        anchors = draft.get("anchors", [])
        if not anchors:
            raise RuntimeError("calibration fixture has no anchor to edit")
        command = AnchorCommand.create(
            command_id="m7-anchor-command",
            sequence=len(draft.get("commands", [])) + 1,
            expected_draft_revision=initial_revision,
            anchor_id=anchors[0]["anchor_id"],
            operation="set_state",
            state="accepted",
            operator_id="m7-operator",
        )
        update_sample, updated = _sample(
            client,
            "calibration_draft_update",
            "PUT",
            f"{path}?proposal_revision_id={CALIBRATION_PROPOSAL_REVISION}",
            json={
                "draft_id": DRAFT_ID,
                "expected_revision": initial_revision,
                "command": command.to_mapping(),
            },
        )
        updated_draft = updated.get("draft", {}) if isinstance(updated, dict) else {}
        if (
            update_sample["status_code"] != 200
            or updated_draft.get("revision") != initial_revision + 1
            or updated_draft.get("commands", [])[-1].get("command_id") != command.command_id
        ):
            update_sample.update(ok=False, error="calibration command was not durably applied")
        samples.append(update_sample)
        read_sample, readback = _sample(
            client,
            "calibration_draft_readback_after_update",
            "GET",
            f"{path}?proposal_revision_id={CALIBRATION_PROPOSAL_REVISION}&draft_id={DRAFT_ID}",
        )
        persisted = readback.get("draft", {}) if isinstance(readback, dict) else {}
        if persisted != updated_draft:
            read_sample.update(ok=False, error="calibration draft readback differs from update")
        samples.append(read_sample)
        effects.append(
            {
                "effect": "calibration_draft_revision",
                "expected": initial_revision + 1,
                "actual": persisted.get("revision"),
            }
        )
        discard_sample, discarded = _sample(
            client,
            "calibration_draft_discard",
            "POST",
            f"{path}/discard",
            json={
                "proposal_revision_id": CALIBRATION_PROPOSAL_REVISION,
                "draft_id": DRAFT_ID,
            },
        )
        discarded_draft = discarded.get("draft", {}) if isinstance(discarded, dict) else {}
        if (
            discard_sample["status_code"] != 200
            or discarded_draft.get("commands") != initial_commands
        ):
            discard_sample.update(
                ok=False, error="calibration discard did not restore a clean draft"
            )
        samples.append(discard_sample)
        effects.append(
            {
                "effect": "calibration_discard_commands",
                "expected": initial_commands,
                "actual": discarded_draft.get("commands"),
            }
        )


def _measure_pipeline_run_submission(
    root: Path,
    samples: list[dict[str, Any]],
    effects: list[dict[str, Any]],
) -> None:
    from types import SimpleNamespace

    from fastapi import FastAPI

    from dokodetector_backend.automated_pipeline_run import (
        AutomatedPipelineRunService,
        AutomatedPipelineRunStore,
    )
    from dokodetector_backend.errors import register_error_handlers
    from dokodetector_backend.pipeline_run_api import router

    root.mkdir(parents=True)
    app = FastAPI()
    app.include_router(router)
    register_error_handlers(app)
    app.state.automated_pipeline_run_service = AutomatedPipelineRunService(
        store=AutomatedPipelineRunStore(root),
        recording_source_provider=lambda recording_id: SimpleNamespace(
            to_mapping=lambda: {
                "schema_version": "recording-video/v1",
                "recording_id": recording_id,
                "video_sha256": "a" * 64,
            }
        ),
        recording_provider_validator=lambda _recording_id, stages: {
            "stage_requests": stages,
            "providers": {"event_proposals": {"name": "fixture"}},
        },
        round_session_provider=lambda _recording_id: "m7-session",
    )
    app.state.job_manager_service = SimpleNamespace(
        get_manager=lambda: SimpleNamespace(
            accept=lambda _key, _request: SimpleNamespace(id="m7-managed-parent-job")
        )
    )
    payload = {
        "idempotency_key": "8c9ff760-48e4-4d9d-9ce1-3f9d7878b2a7",
        "session_id": "m7-session",
        "round_context": {
            "game_id": "m7-game",
            "round_id": "m7-round",
            "active_players": ["p1", "p2", "p3", "p4"],
            "dealer": "p1",
            "first_trick_leader": "p2",
        },
        "rules_version": "v1",
        "search": {"max_missing_plays": 1, "max_hypotheses": 16, "max_search_nodes": 1000},
        "stage_requests": {
            name: {"configuration": {"stage": name}}
            for name in (
                "event_proposals",
                "visible_card_and_pile_proposals",
                "card_scene_and_calibration",
                "visual_identity_proposals",
                "table_observations",
            )
        },
    }
    path = "/api/recordings/m7-pipeline-recording/pipeline/runs"
    with TestClient(app) as client:
        start_sample, started = _sample(client, "pipeline_run_submit", "POST", path, json=payload)
        if start_sample["status_code"] != 202 or started.get("status") != "accepted":
            start_sample.update(ok=False, error="pipeline run was not accepted")
        samples.append(start_sample)
        if started.get("run_id"):
            read_sample, readback = _sample(
                client,
                "pipeline_run_readback_after_submit",
                "GET",
                f"{path}/{started['run_id']}",
            )
            if (
                read_sample["status_code"] != 200
                or readback.get("run_id") != started["run_id"]
                or readback.get("job_id") != "m7-managed-parent-job"
            ):
                read_sample.update(ok=False, error="pipeline run and job lineage did not persist")
            samples.append(read_sample)
            effects.append(
                {
                    "effect": "pipeline_run_parent_job",
                    "expected": "m7-managed-parent-job",
                    "actual": readback.get("job_id"),
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
