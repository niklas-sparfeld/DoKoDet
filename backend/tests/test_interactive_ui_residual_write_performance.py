from __future__ import annotations

import hashlib

# ruff: noqa: E402
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import numpy as np
from fastapi.testclient import TestClient

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from app_factory import create_test_app
from run_interactive_ui_pipeline_read_performance import (
    CALIBRATION_PROPOSAL_REVISION,
    CALIBRATION_RECORDING,
    DEFAULT_CACHE,
    DRAFT_ID,
    _link_hard_snapshot,
    _prepare_current_calibration_draft_fixture,
)
from run_interactive_ui_pipeline_read_performance import (
    _settings as _hard_settings,
)
from test_observation_pipeline_api import (
    _exact_input_refs,
    _make_analysis_metadata,
    _wait_observation,
)
from test_visible_card_pipeline_api import (
    RECORDING_ID,
    _EventProvider,
    _FrameResolver,
    _install_recording,
    _PileDetector,
    _selected_node_input,
    _settings,
    _wait,
    _wait_event,
)
from test_visual_identity_pipeline_api import _IdentityProvider, _wait_identity


def _timed_post(client: TestClient, name: str, path: str, **kwargs: object):
    started = time.perf_counter_ns()
    response = client.post(path, **kwargs)
    duration_ns = time.perf_counter_ns() - started
    return response, {
        "case": name,
        "method": "POST",
        "path": path,
        "duration_ns": duration_ns,
        "status_code": response.status_code,
        "response_bytes": len(response.content),
        "response_sha256": hashlib.sha256(response.content).hexdigest(),
        "ok": response.status_code in {200, 201, 202},
    }


def _retain_samples(samples: list[dict[str, object]]) -> None:
    output = os.environ.get("DOKODETECTOR_M8_SAMPLE_OUTPUT")
    if output is None:
        return
    path = Path(output)
    retained = (
        json.loads(path.read_text())
        if path.exists()
        else {
            "scope": "Epic 0114 M8 residual write API responses",
            "measurement": "one in-process TestClient response per named case",
            "qualification": "preliminary samples; not a baseline",
            "samples": [],
        }
    )
    retained["samples"].extend(samples)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(retained, indent=2) + "\n")


def test_residual_stage_and_round_analysis_writes_have_timing_and_durable_readback(
    tmp_path: Path,
) -> None:
    _install_recording(tmp_path)
    session_id = "session-m8-residual-writes"
    _make_analysis_metadata(tmp_path, session_id=session_id)
    app = create_test_app(
        _settings(tmp_path),
        run_round_analysis_synchronously=True,
        event_provider=_EventProvider(),
        visible_card_provider=_PileDetector(),
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=_IdentityProvider(),
    )
    samples: list[dict[str, object]] = []
    with TestClient(app) as client:
        event_response, sample = _timed_post(
            client,
            "event_stage_submission",
            "/api/jobs",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "type": "event_processing",
                "context": {"recording_id": RECORDING_ID},
                "request": {"run_id": "m8-events"},
            },
        )
        samples.append(sample)
        assert event_response.status_code == 202, event_response.text
        event_job_id = event_response.json()["id"]
        event_result = _wait_event(client, event_job_id)
        event_revision_id = event_result["state"]["output_revision_ids"][0]
        event_job = client.get(f"/api/jobs/{event_job_id}").json()
        assert event_job["context"]["recording_id"] == RECORDING_ID
        assert event_job["id"] == event_job_id
        assert event_revision_id

        visible_input = _selected_node_input(client, "events", event_revision_id)
        visible_response, sample = _timed_post(
            client,
            "visible_card_stage_submission",
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={"run_id": "m8-visible", "configuration": {"threshold": 0.5}, **visible_input},
        )
        samples.append(sample)
        assert visible_response.status_code == 202, visible_response.text
        visible_run_id = visible_response.json()["run_id"]
        visible_job = _wait(client, visible_run_id)
        assert visible_job["state"]["status"] == "complete", visible_job
        visible_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{visible_run_id}/result"
        ).json()
        visible_revision_id = visible_result["state"]["output_revision_ids"][0]
        assert visible_result["request"]["input_revision_ids"] == [event_revision_id]
        visible_revision_input = _selected_node_input(client, "visible_cards", visible_revision_id)

        proposal_response, sample = _timed_post(
            client,
            "proposed_card_scene_stage_submission",
            f"/api/recordings/{RECORDING_ID}/pipeline/proposed-card-scenes",
            json={"run_id": "m8-proposed-scenes", **visible_revision_input},
        )
        samples.append(sample)
        assert proposal_response.status_code == 202, proposal_response.text
        proposal_run_id = proposal_response.json()["run_id"]
        proposal_runs = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/proposed-card-scenes"
        ).json()["runs"]
        proposal_run = next(run for run in proposal_runs if run["run_id"] == proposal_run_id)
        assert proposal_run["request"]["input_revision_ids"] == [visible_revision_id]
        proposal_job = client.get(f"/api/jobs/{proposal_run_id}").json()
        assert proposal_job["context"]["recording_id"] == RECORDING_ID

        identity_response, sample = _timed_post(
            client,
            "visual_identity_stage_submission",
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={"run_id": "m8-identities", **visible_revision_input},
        )
        samples.append(sample)
        assert identity_response.status_code == 202, identity_response.text
        identity_run_id = identity_response.json()["run_id"]
        identity_result = _wait_identity(client, identity_run_id)
        assert identity_result["state"]["status"] == "complete", identity_result
        identity_revision_id = identity_result["state"]["output_revision_ids"][0]
        assert identity_result["request"]["input_revision_ids"] == [visible_revision_id]

        input_refs = _exact_input_refs(
            app, [event_revision_id, visible_revision_id, identity_revision_id]
        )
        observation_response, sample = _timed_post(
            client,
            "observation_stage_submission",
            f"/api/recordings/{RECORDING_ID}/pipeline/observations",
            json={"run_id": "m8-observations", "input_node_refs": input_refs},
        )
        samples.append(sample)
        assert observation_response.status_code == 202, observation_response.text
        observation_run_id = observation_response.json()["run_id"]
        observation_result = _wait_observation(client, observation_run_id)
        assert observation_result["state"]["status"] == "complete", observation_result
        observation_revision_id = observation_result["state"]["output_revision_ids"][0]
        assert observation_result["request"]["input_revision_ids"] == [
            event_revision_id,
            visible_revision_id,
            identity_revision_id,
        ]

        observation_node, _ = app.state.pipeline_selection_store.node_store.find_revision(
            observation_revision_id
        )
        observation_ref = {
            "node_id": observation_node.node_id,
            "revision_id": observation_revision_id,
        }
        explicit_payload = {
            "analysis_id": "550e8400-e29b-41d4-a716-446655440091",
            "recording_id": RECORDING_ID,
            "round_id": "round-m8",
            "session_id": session_id,
            "table_observation_node_ref": observation_ref,
            "round_context": {
                "game_id": "game-m8",
                "round_id": "round-m8",
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
        }
        explicit_response, sample = _timed_post(
            client, "round_analysis_explicit_intake", "/v1/round-analyses", json=explicit_payload
        )
        samples.append(sample)
        assert explicit_response.status_code == 202, explicit_response.text
        explicit = explicit_response.json()
        assert explicit["analysis_id"] == explicit_payload["analysis_id"]
        explicit_readback = client.get(f"/v1/round-analyses/{explicit['analysis_id']}").json()
        assert explicit_readback["analysis_id"] == explicit["analysis_id"]
        assert explicit_readback["recording_id"] == RECORDING_ID

        recording_response, sample = _timed_post(
            client,
            "round_analysis_recording_intake",
            f"/v1/recordings/{RECORDING_ID}/round-analyses",
        )
        samples.append(sample)
        assert recording_response.status_code == 202, recording_response.text
        recording_analysis = recording_response.json()
        assert recording_analysis["recording_id"] == RECORDING_ID
        assert recording_analysis["session_id"] == session_id
        recording_readback = client.get(
            f"/v1/round-analyses/{recording_analysis['analysis_id']}"
        ).json()
        assert recording_readback["analysis_id"] == recording_analysis["analysis_id"]
        assert recording_readback["recording_id"] == RECORDING_ID

    assert len(samples) == 7
    assert all(sample["ok"] and sample["duration_ns"] > 0 for sample in samples)
    _retain_samples(samples)


def test_calibration_apply_has_timing_and_published_readback(tmp_path: Path) -> None:
    from doko_operations.card_plane_geometry import TablePlaneCalibration, project_fixed_card
    from table_evidence_analyzer import AnchorCommand, AnchorObservation, CalibrationDraft

    from dokodetector_backend.app import create_app
    from dokodetector_backend.poc_analyzer import create_local_poc_analyzer

    _link_hard_snapshot(tmp_path, DEFAULT_CACHE)
    _prepare_current_calibration_draft_fixture(tmp_path)
    app = create_app(_hard_settings(tmp_path), analyzer=create_local_poc_analyzer())
    path = f"/api/recordings/{CALIBRATION_RECORDING}/pipeline/calibration-refinement"
    with TestClient(app) as client:
        start = client.post(
            path,
            json={"proposal_revision_id": CALIBRATION_PROPOSAL_REVISION, "draft_id": DRAFT_ID},
        )
        assert start.status_code == 201, start.text
        draft = start.json()["draft"]
        app.state.calibration_refinement_service.store.publish_initial(
            CalibrationDraft.from_mapping(draft)
        )
        source_draft = CalibrationDraft.from_mapping(draft)
        service = app.state.calibration_refinement_service
        _proposal, source, proposal_data = service._proposal(
            CALIBRATION_RECORDING, CALIBRATION_PROPOSAL_REVISION
        )
        source_node, source_revision = service._find_node_revision(
            source.manifest.revision_id, "visible_cards"
        )
        detector_producer = source_revision.metadata["producer"]
        detector_run_id = detector_producer["run_id"]
        detector_attempt = source.manifest.revision_id.rsplit("-attempt-", 1)[1]
        source_coverage = source_revision.metadata.get("coverage", {})
        event_ref = source_coverage.get("event_set_ref")
        event_set = None
        event_sets = []
        if isinstance(event_ref, dict):
            event_set = app.state.event_set_store.get(
                CALIBRATION_RECORDING, event_ref["set_id"], event_ref["version"]
            )
            assert event_set is not None
            event_sets = [
                {
                    "set_id": event_ref["set_id"],
                    "version": event_ref["version"],
                    "content_sha256": event_set["content_sha256"],
                }
            ]
            event_ids = {item["event_id"] for item in event_set["content"]["events"]}
        else:
            event_ids = set()

        def detection(
            object_id: str, kind: str, side: str | None, polygons: Any, width: int, height: int
        ):
            return {
                "object_id": object_id,
                "kind": kind,
                "side": side,
                "segments": [
                    {
                        "segment_id": f"segment-{index:04d}",
                        "polygon": [
                            {
                                "x": round(
                                    point["x"]
                                    if isinstance(point, dict)
                                    else point[0] * width / 1000
                                ),
                                "y": round(
                                    point["y"]
                                    if isinstance(point, dict)
                                    else point[1] * height / 1000
                                ),
                            }
                            for point in polygon
                        ],
                    }
                    for index, polygon in enumerate(polygons)
                ],
            }

        fixture_calibration = TablePlaneCalibration.from_mapping(proposal_data.calibration)

        def detection_polygon(candidate, identity, *, edited: bool) -> list[dict[str, int]]:
            source_point = np.asarray(
                [
                    identity.width / 2,
                    identity.height / 2,
                    1.0,
                ]
            )
            table_point = np.asarray(fixture_calibration.image_to_table) @ source_point
            table_center = table_point[:2] / table_point[2]
            if edited:
                table_center[0] += 0.25
            projected = project_fixed_card(
                fixture_calibration.table_to_image,
                table_center,
                0.0,
                fixture_calibration.card_short_size,
                fixture_calibration.card_long_size,
            )
            return [{"x": round(point[0]), "y": round(point[1])} for point in projected]

        detection_frames = []
        edited_geometry_frame_id = None
        reviewed_geometry_frame_id = None
        for outcome in source.content.outcomes:
            if outcome.status == "failed" or outcome.frame_identity is None:
                continue
            identity = outcome.frame_identity
            event_ids_for_frame = (
                [
                    {
                        "set_id": event_ref["set_id"],
                        "version": event_ref["version"],
                        "event_id": outcome.event_id,
                    }
                ]
                if isinstance(event_ref, dict) and outcome.event_id in event_ids
                else []
            )
            edited_frame = bool(outcome.candidates) and edited_geometry_frame_id is None
            if edited_frame:
                edited_geometry_frame_id = outcome.event_id
            reviewed_empty_frame = (
                bool(outcome.candidates) and not edited_frame and reviewed_geometry_frame_id is None
            )
            if reviewed_empty_frame:
                reviewed_geometry_frame_id = outcome.event_id
            detections = (
                [
                    detection(
                        outcome.candidates[0].card_id,
                        "visible_card",
                        outcome.candidates[0].side,
                        [detection_polygon(outcome.candidates[0], identity, edited=edited_frame)],
                        identity.width,
                        identity.height,
                    )
                ]
                if outcome.candidates and not reviewed_empty_frame
                else []
            )
            detection_frames.append(
                {
                    "frame_id": outcome.event_id,
                    "frame_identity": identity.to_mapping(),
                    "event_ids": event_ids_for_frame,
                    "detections": detections,
                }
            )

        from types import SimpleNamespace

        from dokodetector_backend.detection_set_store import DetectionSetStore

        class RecordingFolders:
            def get(self, recording_id: str):
                assert recording_id == CALIBRATION_RECORDING
                return SimpleNamespace(media={"sha256": source.manifest.source.video_sha256})

            def recording_path(self, recording_id: str) -> Path:
                assert recording_id == CALIBRATION_RECORDING
                return tmp_path / "recording-folder" / recording_id

        class EventSets:
            def get(self, recording_id: str, set_id: str, version: str):
                if (
                    isinstance(event_ref, dict)
                    and recording_id == CALIBRATION_RECORDING
                    and set_id == event_ref["set_id"]
                    and version == event_ref["version"]
                ):
                    return event_set
                return None

        detection_sets = DetectionSetStore(RecordingFolders(), EventSets())
        service.detection_set_store = detection_sets
        source_detection_set = detection_sets.save(
            CALIBRATION_RECORDING,
            set_id=f"detector-{detector_run_id}",
            version=detector_attempt,
            origin="processor",
            source={"source_video_sha256": source.manifest.source.video_sha256},
            producer=detector_producer,
            event_sets=event_sets,
            frames=detection_frames,
        )
        input_detection_set_ref = {
            "set_id": source_detection_set["set_id"],
            "version": source_detection_set["version"],
            "content_sha256": source_detection_set["content_sha256"],
        }
        selected_data = service._calibration_detection_set_proposal_data(
            CALIBRATION_RECORDING,
            source,
            source_detection_set,
            proposal_data.calibration,
            {
                "source_proposal_revision_id": CALIBRATION_PROPOSAL_REVISION,
                "input_detection_set_ref": input_detection_set_ref,
            },
        )
        build_calibration_detection_data = service._calibration_detection_set_proposal_data

        def reuse_exact_base_detection_data(
            selected_recording_id, selected_source, detection_set, selected_calibration, diagnostics
        ):
            parsed = TablePlaneCalibration.from_mapping(
                selected_calibration
                if isinstance(selected_calibration, dict)
                else selected_calibration.to_mapping()
            )
            if parsed.calibration_digest == proposal_data.calibration_digest:
                return selected_data
            return build_calibration_detection_data(
                selected_recording_id,
                selected_source,
                detection_set,
                selected_calibration,
                diagnostics,
            )

        service._calibration_detection_set_proposal_data = reuse_exact_base_detection_data
        assert edited_geometry_frame_id is not None
        original_geometry_scene = next(
            frame.proposal.initialized_scene
            for frame in proposal_data.frames
            if frame.frame_id == edited_geometry_frame_id and frame.proposal is not None
        )
        selected_geometry_scene = next(
            frame.proposal.initialized_scene
            for frame in selected_data.frames
            if frame.frame_id == edited_geometry_frame_id and frame.proposal is not None
        )
        assert selected_geometry_scene != original_geometry_scene
        from doko_operations.card_plane_calibration_refinement import (
            build_calibration_preview,
            exclude_anchors_in_reviewed_ignore_regions,
        )

        frame_scenes = service._calibration_detection_set_frame_scenes(
            CALIBRATION_RECORDING, CALIBRATION_PROPOSAL_REVISION, selected_data
        )
        source_draft = exclude_anchors_in_reviewed_ignore_regions(source_draft, frame_scenes)
        # Use exact planar outlines from the active calibration. The hard snapshot's
        # detector anchors are intentionally noisy, so they cannot prove a successful apply.
        ignored_frame_ids = {
            frame_id
            for item in frame_scenes
            if isinstance(item.get("ignored_regions"), list) and item["ignored_regions"]
            for frame_id in (
                item.get("item_id"),
                item.get("event_id"),
                (item.get("frame_identity") or {}).get("frame_id"),
                (((item.get("card_scene") or {}).get("reviewed") or {}).get("scene") or {}).get(
                    "source_frame_id"
                ),
            )
            if isinstance(frame_id, str)
        }
        eligible_by_frame = {
            anchor.source_frame_id: anchor
            for anchor in source_draft.anchors
            if anchor.eligible and anchor.source_frame_id not in ignored_frame_ids
        }
        source_anchors = list(eligible_by_frame.values())[:9]
        assert len(source_anchors) == 9
        frame_ids = [f"m8-synthetic-frame-{index}" for index in range(9)]
        base_calibration = TablePlaneCalibration.from_mapping(proposal_data.calibration)
        table_to_image = np.asarray(base_calibration.table_to_image, dtype=np.float64)
        table_to_image[2, :2] *= 0.1
        positions = [
            (0.0, 0.0),
            (4.0, 0.0),
            (8.0, 0.0),
            (0.0, 3.0),
            (4.0, 3.0),
            (8.0, 3.0),
            (0.0, 6.0),
            (4.0, 6.0),
            (8.0, 6.0),
        ]
        anchors = []
        commands = []
        for index, (frame_id, center, source_anchor) in enumerate(
            zip(frame_ids, positions, source_anchors, strict=True)
        ):
            anchor = AnchorObservation.create(
                anchor_id=f"m8-synthetic-anchor-{index}",
                card_id=f"m8-synthetic-card-{index}",
                source_frame_id=frame_id,
                source_frame_digest=source_anchor.source_frame_digest,
                detector_revision_id=source.manifest.revision_id,
                quadrilateral=project_fixed_card(
                    table_to_image,
                    center,
                    (index % 3) * 8.0,
                    base_calibration.card_short_size,
                    base_calibration.card_long_size,
                ).tolist(),
                confidence=1.0,
                temporal_bin=f"m8-t-{index}",
                table_region_bin=f"m8-r-{index}",
                scale_bin="m8-s-1",
                orientation_bin=f"m8-o-{index % 3}",
                eligible=True,
                eligibility_reason=None,
                state="accepted",
                weight_class="accepted",
            )
            anchors.append(anchor)
            commands.append(
                AnchorCommand.create(
                    command_id=f"m8-anchor-command-{index}",
                    sequence=index + 1,
                    expected_draft_revision=source_draft.revision + index,
                    anchor_id=anchor.anchor_id,
                    operation="set_state",
                    state="accepted",
                    operator_id="m8-operator",
                )
            )
        updated_draft = CalibrationDraft.create(
            draft_id=source_draft.draft_id,
            recording_id=source_draft.recording_id,
            detector_revision_id=source_draft.detector_revision_id,
            detector_revision_digest=source_draft.detector_revision_digest,
            base_calibration_revision_id=source_draft.base_calibration_revision_id,
            base_calibration_digest=source_draft.base_calibration_digest,
            source_frame_digests={
                **dict(source_draft.source_frame_digests),
                **{
                    frame_id: source_anchor.source_frame_digest
                    for frame_id, source_anchor in zip(frame_ids, source_anchors, strict=True)
                },
            },
            anchors=anchors,
            commands=commands,
            revision=source_draft.revision + len(commands),
            state=source_draft.state,
        )
        app.state.calibration_refinement_service.store.publish(updated_draft)
        persisted_draft = updated_draft.to_mapping()

        effective_draft = exclude_anchors_in_reviewed_ignore_regions(
            CalibrationDraft.from_mapping(persisted_draft), frame_scenes
        )
        preview = build_calibration_preview(
            effective_draft, base_calibration, frame_scenes=frame_scenes
        )
        assert preview.candidate_calibration is not None, preview.to_mapping()
        preview_digest = preview.preview_digest

        # The M4 hard snapshot contains the source and proposal nodes but no migrated
        # maintained visible-card node. Seed that exact canonical node for the apply path.

        from table_evidence_analyzer.pipeline_data import VisibleCardData

        from dokodetector_backend.calibration_reflow_context import (
            build_calibration_reflow_context,
        )
        from dokodetector_backend.lineage_draft_projection import (
            project_visible_card_items,
        )
        from dokodetector_backend.pipeline_item_provenance import _items
        from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
        from dokodetector_backend.visible_card_node_draft import (
            VisibleCardNodeDraft,
            VisibleCardNodeDraftItem,
        )

        key = f"maintained_draft/{CALIBRATION_RECORDING}/visible_cards"
        visible_node_id = str(uuid5(NAMESPACE_URL, f"lineage-draft:{key}"))
        node_store = app.state.pipeline_selection_store.node_store
        visible_data = (
            source.content
            if isinstance(source.content, VisibleCardData)
            else VisibleCardData.from_mapping(source.content)
        )
        empty_detection_frame_ids = {
            frame["frame_id"] for frame in detection_frames if not frame["detections"]
        }
        reviewed_frame_id = next(
            item.event_id
            for item in visible_data.outcomes
            if item.event_id in empty_detection_frame_ids
        )
        visible_items = tuple(
            VisibleCardNodeDraftItem(
                item_id=outcome.event_id,
                base_item_id=None,
                review_state=("accepted" if outcome.event_id == reviewed_frame_id else "pending"),
                item=outcome.to_mapping(),
            )
            for outcome in visible_data.outcomes
        )
        visible_draft = VisibleCardNodeDraft(
            revision=0,
            source_revision_id=source.manifest.revision_id,
            proposal_revision_id=CALIBRATION_PROPOSAL_REVISION,
            items=visible_items,
            coverage=None,
            impact=(),
            updated_at="2026-11-07T00:00:00Z",
        )
        projection = project_visible_card_items(
            visible_items,
            coverage=None,
            impact=(),
            proposal_revision_id=CALIBRATION_PROPOSAL_REVISION,
        )
        node_store.create(
            visible_node_id,
            "M8 canonical visible-card draft",
            "visible_cards",
            source.manifest.source.to_mapping(),
            projection["content"],
            {
                "migration": {"legacy_key": key, "draft_sha256": "0" * 64},
                "calibration_reflow_context": build_calibration_reflow_context(visible_draft),
                "scene_only_frame_ids": projection["scene_only_items"],
                "item_provenance": {
                    "version": 1,
                    "items": _items(projection["content"], projection["pointers"]),
                    "changes": [],
                },
            },
            revision_id=str(uuid5(NAMESPACE_URL, f"m8-visible-draft:{CALIBRATION_RECORDING}")),
        )
        PipelineNodeReviews(node_store).item(
            "m8-review-empty-frame",
            visible_node_id,
            str(uuid5(NAMESPACE_URL, f"m8-visible-draft:{CALIBRATION_RECORDING}")),
            reviewed_frame_id,
            "Keep the reviewed frame decision through calibration reflow?",
            "accepted",
            {"kind": "human", "id": "m8-reviewer"},
            {
                "frame_sha256": next(
                    outcome.frame_identity.image_sha256
                    for outcome in visible_data.outcomes
                    if outcome.event_id == reviewed_frame_id and outcome.frame_identity is not None
                ),
                "policy": "frame/v1",
            },
        )
        assert (
            next(
                item.review_state
                for item in service._current_node_draft(
                    CALIBRATION_RECORDING, CALIBRATION_PROPOSAL_REVISION
                ).items
                if item.item_id == reviewed_frame_id
            )
            == "accepted"
        )
        frame_scenes = service._calibration_detection_set_frame_scenes(
            CALIBRATION_RECORDING, CALIBRATION_PROPOSAL_REVISION, selected_data
        )
        effective_draft = exclude_anchors_in_reviewed_ignore_regions(
            CalibrationDraft.from_mapping(persisted_draft), frame_scenes
        )
        preview = build_calibration_preview(
            effective_draft, base_calibration, frame_scenes=frame_scenes
        )
        assert preview.candidate_calibration is not None, preview.to_mapping()
        preview_digest = preview.preview_digest

        apply_path = f"{path}/apply?proposal_revision_id={CALIBRATION_PROPOSAL_REVISION}"
        applied, sample = _timed_post(
            client,
            "calibration_apply",
            apply_path,
            json={
                "draft_id": DRAFT_ID,
                "expected_revision": persisted_draft["revision"],
                "preview_digest": preview_digest,
                "input_detection_set_ref": input_detection_set_ref,
                "operator_id": "m8-operator",
                "confirm_affected": True,
            },
        )
        assert applied.status_code == 200, applied.text
        result = applied.json()
        assert result["action"] == "applied"
        assert result["recording_id"] == CALIBRATION_RECORDING
        reflow_set = detection_sets.get(
            CALIBRATION_RECORDING,
            result["detection_set_ref"]["set_id"],
            result["detection_set_ref"]["version"],
        )
        assert reflow_set is not None
        assert reflow_set["content_sha256"] == result["detection_set_ref"]["content_sha256"]
        assert reflow_set["producer"]["input_detection_set_ref"] == {
            "set_id": source_detection_set["set_id"],
            "version": source_detection_set["version"],
            "content_sha256": source_detection_set["content_sha256"],
        }
        assert reflow_set["content"] == source_detection_set["content"]
        reopened_store = DetectionSetStore(RecordingFolders(), EventSets())
        reopened_set = reopened_store.get(
            CALIBRATION_RECORDING,
            result["detection_set_ref"]["set_id"],
            result["detection_set_ref"]["version"],
        )
        assert reopened_set is not None
        assert reopened_set["content_sha256"] == result["detection_set_ref"]["content_sha256"]
        assert reopened_set["content"] == source_detection_set["content"]
        _, _, applied_proposal_data = service._proposal(
            CALIBRATION_RECORDING, result["proposal_revision_id"]
        )
        applied_geometry_scene = next(
            frame.proposal.initialized_scene
            for frame in applied_proposal_data.frames
            if frame.frame_id == edited_geometry_frame_id and frame.proposal is not None
        )
        assert applied_geometry_scene != original_geometry_scene
        current_visible_draft = service._current_node_draft(
            CALIBRATION_RECORDING, result["proposal_revision_id"]
        )
        preserved_review = next(
            item for item in current_visible_draft.items if item.item_id == reviewed_frame_id
        )
        assert preserved_review.review_state in {"accepted", "affected"}
        calibration = client.get(
            f"/api/recordings/{CALIBRATION_RECORDING}/pipeline/calibrations/"
            f"{result['calibration_revision_id']}"
        )
        assert calibration.status_code == 200, calibration.text
        assert calibration.json()["calibration_revision_id"] == result["calibration_revision_id"]
        visible_ref = result["visible_card_node_ref"]
        visible_revision = client.get(
            f"/api/pipeline/nodes/{visible_ref['node_id']}/revisions/{visible_ref['revision_id']}"
        )
        assert visible_revision.status_code == 200, visible_revision.text
        assert visible_revision.json()["revision_id"] == visible_ref["revision_id"]
        assert sample["duration_ns"] > 0
        _retain_samples([sample])
