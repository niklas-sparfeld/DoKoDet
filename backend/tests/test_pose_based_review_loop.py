from __future__ import annotations

import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
from doko_operations.card_plane_calibration import calibrate_recording
from doko_operations.card_plane_geometry import (
    CardPose,
    CardStackingOrder,
    ReviewedCardScene,
    derive_pose_scene_visible_regions,
    project_fixed_card,
)
from doko_operations.card_plane_initialization import initialize_card_scene
from doko_operations.pipeline_data import (
    CARD_STATE_CHANGED_EVENT_TYPE,
    DataRevision,
    EventData,
    EventRecord,
    ProcessorProducer,
    RecordingVideoSource,
    canonical_event_data_bytes,
    sha256_bytes,
)
from doko_operations.pipeline_dataset import (
    PipelineDatasetRequest,
    PipelineDatasetSourceGroup,
    materialize_pipeline_dataset,
)
from table_evidence_analyzer.pipeline_data import (
    VisibleCardData,
    canonical_visible_card_data_bytes,
)

from dokodetector_backend.pipeline_reference_service import PipelineReferenceService
from dokodetector_backend.pipeline_reference_store import PipelineReferenceStore
from dokodetector_backend.pipeline_store import (
    PipelineRevisionStore,
    PipelineRuntimeStorage,
    PipelineSelectionStore,
    ProcessorRunStore,
)

DIGEST = "a" * 64
TABLE_TO_IMAGE = np.asarray(
    [[120.0, 20.0, 420.0], [15.0, 100.0, 240.0], [0.0002, 0.0004, 1.0]],
    dtype=np.float64,
)
SOURCE = RecordingVideoSource(
    recording_id="recording-0072-m5",
    relative_path="recordings/recording-0072-m5/video.mov",
    video_sha256=DIGEST,
    byte_length=100,
    duration_us=12_000_000,
)


class _Settings:
    repository_root = Path(".").resolve()


class _RecordingStore:
    def get(self, recording_id: str) -> None:
        del recording_id
        return None


class _RepositoryStorage:
    pass


def _service(
    tmp_path: Path,
) -> tuple[PipelineReferenceService, PipelineRevisionStore]:
    revision_store = PipelineRevisionStore(tmp_path / "runtime")
    run_store = ProcessorRunStore(
        PipelineRuntimeStorage(tmp_path / "runtime"), revision_store=revision_store
    )
    selection_store = PipelineSelectionStore(
        PipelineRuntimeStorage(tmp_path / "runtime"),
        revision_store=revision_store,
        run_store=run_store,
    )
    service = PipelineReferenceService(
        _Settings(),
        _RecordingStore(),
        _RepositoryStorage(),
        reference_store=PipelineReferenceStore(tmp_path / "operations" / "pipeline-references"),
        revision_store=revision_store,
        selection_store=selection_store,
    )
    return service, revision_store


def _frame_identity(index: int) -> dict[str, Any]:
    timestamp_us = index * 1_000_000
    return {
        "schema_version": "exact-event/v1",
        "source_video_sha256": DIGEST,
        "requested_time_us": timestamp_us,
        "frame_index": index,
        "presentation_timestamp_us": timestamp_us,
        "width": 1920,
        "height": 1080,
        "decoder_version": "fixture-decoder/v1",
        "transform_version": "fixture-transform/v1",
        "output_encoding": "png",
        "content_type": "image/png",
        "image_sha256": DIGEST,
        "policy": "exact-event/v1",
    }


def _calibration_result() -> dict[str, Any]:
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
        (2.0, 1.5),
        (6.0, 4.5),
        (10.0, 7.0),
    ]
    frames: list[dict[str, Any]] = []
    for index, center in enumerate(positions):
        polygon = project_fixed_card(TABLE_TO_IMAGE, center, (index % 3) * 8.0, 1.0, 1.5)
        predictions: list[dict[str, Any]] = [
            {
                "candidate_id": f"calibration-candidate-{index:02d}",
                "confidence": 0.98,
                "provider": "local-fixture-provider",
                "bundle": "local-fixture-bundle",
                "polygon": polygon.tolist(),
            }
        ]
        if index == 0:
            predictions.append(
                {
                    "candidate_id": "calibration-duplicate",
                    "confidence": 0.97,
                    "provider": "local-fixture-provider",
                    "bundle": "local-fixture-bundle",
                    "polygon": polygon.tolist(),
                }
            )
        frames.append(
            {
                "frame_id": f"calibration-frame-{index:02d}",
                "frame_index": index * 30,
                "timestamp_us": index * 1_000_000,
                "width": 1920,
                "height": 1080,
                "source_transform": "fixture-transform-1",
                "predictions": predictions,
            }
        )
    return {
        "recording_id": SOURCE.recording_id,
        "source_revision": "generated-local-0072-m5",
        "frames": frames,
    }


def _scenario_result(
    scenario: str,
    index: int,
    cards: list[tuple[str, tuple[float, float], float]],
) -> dict[str, Any]:
    predictions = [
        {
            "candidate_id": suggestion_id,
            "confidence": 0.97,
            "provider": "local-fixture-provider",
            "bundle": "local-fixture-bundle",
            "polygon": project_fixed_card(TABLE_TO_IMAGE, center, angle, 1.0, 1.5).tolist(),
        }
        for suggestion_id, center, angle in cards
    ]
    return {
        "recording_id": SOURCE.recording_id,
        "source_revision": "generated-local-0072-m5",
        "frames": [
            {
                "frame_id": f"review-{scenario}",
                "frame_index": index,
                "timestamp_us": index * 1_000_000,
                "width": 1920,
                "height": 1080,
                "source_transform": "fixture-transform-1",
                "predictions": predictions,
            }
        ],
    }


def _pose_envelope(
    scene: ReviewedCardScene,
    calibration: Any,
    *,
    initialized_scene: ReviewedCardScene | None = None,
) -> dict[str, Any]:
    projection = {
        "table_to_image_homography": [list(row) for row in calibration.table_to_image],
        "card_short_size": calibration.card_short_size,
        "card_long_size": calibration.card_long_size,
    }
    derivation = derive_pose_scene_visible_regions(scene, projection)
    return {
        "schema_version": "reviewed-card-scene-editor/v1",
        "scene": scene.to_mapping(),
        "initialized_scene": (initialized_scene or scene).to_mapping(),
        "projection": projection,
        "derived_region_receipt": derivation.receipt.to_mapping(),
    }


def _candidates_for_scene(
    scene: ReviewedCardScene,
    calibration: Any,
    *,
    source_suggestion_ids: dict[str, str],
) -> list[dict[str, Any]]:
    projection = {
        "table_to_image_homography": [list(row) for row in calibration.table_to_image],
        "card_short_size": calibration.card_short_size,
        "card_long_size": calibration.card_long_size,
    }
    derivation = derive_pose_scene_visible_regions(scene, projection)
    return [
        {
            "card_id": region["card_id"],
            "geometry": region["geometry"],
            "normalization": region["normalization"],
            "side": "unknown",
            "model_scores": [{"producer_id": "local-fixture-provider", "score": 0.97}]
            if region["card_id"] in source_suggestion_ids
            else None,
        }
        for region in derivation.regions
    ]


def _corrected_scene(
    scene: ReviewedCardScene,
    *,
    center_offsets: dict[str, tuple[float, float]] | None = None,
    rotations: dict[str, float] | None = None,
    order: tuple[str, ...] | None = None,
    remove_card_id: str | None = None,
    add_card: CardPose | None = None,
) -> ReviewedCardScene:
    center_offsets = center_offsets or {}
    rotations = rotations or {}
    poses: list[CardPose] = []
    for pose in scene.poses:
        if pose.card_id == remove_card_id:
            continue
        offset = center_offsets.get(pose.card_id, (0.0, 0.0))
        poses.append(
            CardPose(
                card_id=pose.card_id,
                center=(pose.center[0] + offset[0], pose.center[1] + offset[1]),
                rotation_degrees=rotations.get(pose.card_id, pose.rotation_degrees),
                source_suggestion_id=pose.source_suggestion_id,
                fit_diagnostics_digest=pose.fit_diagnostics_digest,
            )
        )
    if add_card is not None:
        poses.append(add_card)
    pose_ids = {pose.card_id for pose in poses}
    requested_order = order or tuple(
        card_id for card_id in scene.stacking_order.card_ids if card_id in pose_ids
    )
    requested_order = tuple(
        [card_id for card_id in requested_order if card_id in pose_ids]
        + sorted(pose_ids.difference(requested_order))
    )
    return ReviewedCardScene.create(
        source_frame_id=scene.source_frame_id,
        source_frame_width=scene.source_frame_width,
        source_frame_height=scene.source_frame_height,
        calibration_revision_id=scene.calibration_revision_id,
        calibration_digest=scene.calibration_digest,
        poses=poses,
        stacking_order=CardStackingOrder(
            card_ids=requested_order,
            uncertain_edges=(),
            contradictions=(),
        ),
    )


def _event_revision(revision_id: str, event_ids: list[str]) -> tuple[DataRevision, EventData]:
    content = EventData(
        events=tuple(
            EventRecord(
                event_id=event_id,
                event_type=CARD_STATE_CHANGED_EVENT_TYPE,
                start_us=index * 1_000_000,
                end_us=index * 1_000_000 + 100_000,
            )
            for index, event_id in enumerate(event_ids)
        )
    )
    manifest = DataRevision(
        revision_id=revision_id,
        content_type="events",
        content_schema="event-data/v1",
        recording_id=SOURCE.recording_id,
        source=SOURCE,
        content_sha256=sha256_bytes(canonical_event_data_bytes(content)),
        input_revision_ids=(),
        origin="processor",
        producer=ProcessorProducer(
            run_id="run-local-events-0072-m5",
            processor_type="event-detection",
            implementation_id="local-fixture-provider/v1",
            model_id="local-fixture-bundle",
        ),
        coverage={"kind": "processed"},
        created_at="2026-09-20T10:00:00Z",
    )
    return manifest, content


def _visible_revision(
    revision_id: str,
    outcomes: list[dict[str, Any]],
) -> tuple[DataRevision, VisibleCardData]:
    content = VisibleCardData.from_mapping(
        {"schema_version": "visible-card-data/v1", "outcomes": outcomes}
    )
    manifest = DataRevision(
        revision_id=revision_id,
        content_type="visible_cards",
        content_schema="visible-card-data/v1",
        recording_id=SOURCE.recording_id,
        source=SOURCE,
        content_sha256=sha256_bytes(canonical_visible_card_data_bytes(content)),
        input_revision_ids=(),
        origin="processor",
        producer=ProcessorProducer(
            run_id="run-local-visible-cards-0072-m5",
            processor_type="visible-card-detection",
            implementation_id="local-fixture-provider/v1",
            model_id="local-fixture-bundle",
        ),
        coverage={"kind": "processed"},
        created_at="2026-09-20T10:00:00Z",
    )
    return manifest, content


def test_local_pose_review_loop_reaches_a_lineage_bound_dataset(tmp_path: Path) -> None:
    calibration_input = _calibration_result()
    started = time.perf_counter()
    calibration_run = calibrate_recording(calibration_input)
    calibration_runtime_ms = round((time.perf_counter() - started) * 1000.0, 3)
    assert calibration_run.status == "published"
    assert calibration_run.calibration is not None
    calibration = calibration_run.calibration

    scenarios = {
        "distant-cards": [("distant-a", (1.0, 1.0), 0.0), ("distant-b", (8.0, 6.0), 12.0)],
        "two-card-overlap": [("two-a", (4.0, 3.0), 0.0), ("two-b", (4.45, 3.1), 5.0)],
        "three-card-overlap": [
            ("three-a", (5.0, 3.0), 0.0),
            ("three-b", (5.3, 3.1), 5.0),
            ("three-c", (5.6, 3.2), 10.0),
        ],
        "wrong-count": [("count-a", (2.0, 5.0), 0.0), ("count-b", (2.4, 5.1), 0.0)],
        "wrong-order": [("order-a", (7.0, 2.0), 0.0), ("order-b", (7.4, 2.1), 0.0)],
    }
    outcomes: list[dict[str, Any]] = []
    reviewed_scenes: dict[str, tuple[ReviewedCardScene, ReviewedCardScene]] = {}
    frame_metrics: list[dict[str, Any]] = []
    for index, (scenario, cards) in enumerate(scenarios.items(), start=1):
        local_result = _scenario_result(scenario, index, cards)
        initialized = initialize_card_scene(local_result, calibration)
        assert initialized.status == "initialized"
        assert initialized.scene is not None
        initial_scene = initialized.scene
        source_suggestion_ids = {
            pose.card_id: pose.source_suggestion_id or "" for pose in initial_scene.poses
        }
        if scenario == "two-card-overlap":
            final_scene = _corrected_scene(
                initial_scene,
                center_offsets={initial_scene.poses[0].card_id: (0.15, -0.1)},
                rotations={initial_scene.poses[1].card_id: 14.0},
            )
            actions = {"moved_cards": 1, "rotations": 1, "reorder_actions": 0}
        elif scenario == "three-card-overlap":
            final_scene = _corrected_scene(
                initial_scene,
                center_offsets={initial_scene.poses[0].card_id: (0.1, -0.1)},
                rotations={initial_scene.poses[1].card_id: 18.0},
                order=tuple(reversed(initial_scene.stacking_order.card_ids)),
            )
            actions = {"moved_cards": 1, "rotations": 1, "reorder_actions": 1}
        elif scenario == "wrong-count":
            removed_id = initial_scene.poses[-1].card_id
            final_scene = _corrected_scene(
                initial_scene,
                remove_card_id=removed_id,
                add_card=CardPose(
                    card_id="manual-card-1",
                    center=(0.0, 0.0),
                    rotation_degrees=8.0,
                    source_suggestion_id=None,
                    fit_diagnostics_digest=None,
                ),
                order=("manual-card-1", initial_scene.poses[0].card_id),
            )
            actions = {"moved_cards": 0, "rotations": 0, "reorder_actions": 0}
            actions.update(additions=1, removals=1)
        elif scenario == "wrong-order":
            final_scene = _corrected_scene(
                initial_scene,
                order=tuple(reversed(initial_scene.stacking_order.card_ids)),
            )
            actions = {"moved_cards": 0, "rotations": 0, "reorder_actions": 1}
        else:
            final_scene = initial_scene
            actions = {"moved_cards": 0, "rotations": 0, "reorder_actions": 0}
        actions.setdefault("additions", 0)
        actions.setdefault("removals", 0)
        reviewed_scenes[scenario] = (initial_scene, final_scene)
        candidates = _candidates_for_scene(
            initial_scene,
            calibration,
            source_suggestion_ids=source_suggestion_ids,
        )
        outcomes.append(
            {
                "event_id": f"event-{scenario}",
                "frame_identity": _frame_identity(index),
                "status": "detected",
                "candidates": candidates,
                "ignored_regions": [],
                "error": None,
                "card_scene": _pose_envelope(
                    initial_scene,
                    calibration,
                    initialized_scene=initial_scene,
                ),
            }
        )
        frame_metrics.append(
            {
                "scenario": scenario,
                "frame_id": initial_scene.source_frame_id,
                "accepted_pose_count": len(initial_scene.poses),
                "final_pose_count": len(final_scene.poses),
                "initial_order": list(initial_scene.stacking_order.card_ids),
                "final_order": list(final_scene.stacking_order.card_ids),
                "ignore_regions": 0,
                "unusable": False,
                **actions,
            }
        )

    unsupported_result = _scenario_result(
        "unsupported-frame", 6, [("unsupported", (4.0, 3.0), 0.0)]
    )
    unsupported_result["frames"][0]["predictions"] = [
        {"candidate_id": "unsupported", "confidence": 0.99, "polygon": [[1.0, 2.0]]}
    ]
    unsupported = initialize_card_scene(unsupported_result, calibration)
    assert unsupported.status == "failed"
    assert unsupported.failure is not None
    assert unsupported.failure.code == "no_initialized_candidates"
    outcomes.append(
        {
            "event_id": "event-unsupported-frame",
            "frame_identity": _frame_identity(6),
            "status": "failed",
            "candidates": [],
            "ignored_regions": [],
            "error": "unsupported external occlusion",
        }
    )
    frame_metrics.append(
        {
            "scenario": "unsupported-frame",
            "frame_id": "review-unsupported-frame",
            "accepted_pose_count": 0,
            "final_pose_count": 0,
            "moved_cards": 0,
            "rotations": 0,
            "reorder_actions": 0,
            "additions": 0,
            "removals": 0,
            "ignore_regions": 0,
            "unusable": True,
            "failure_code": unsupported.failure.code,
        }
    )

    event_ids = [str(outcome["event_id"]) for outcome in outcomes]
    service, revision_store = _service(tmp_path)
    event_manifest, event_content = _event_revision("generated-events-0072-m5", event_ids)
    revision_store.publish(event_manifest, event_content)
    event_reference = service.create_reference(
        SOURCE.recording_id,
        "events",
        {"operator_id": "operator-0072-m5", "source_revision_id": event_manifest.revision_id},
    )
    event_update = service.update_draft(
        SOURCE.recording_id,
        "events",
        {
            "operator_id": "operator-0072-m5",
            "expected_revision": event_reference.draft.revision,
            "operations": [{"operation": "accept", "item_id": event_id} for event_id in event_ids],
        },
    )
    event_completed = service.complete_reference(
        SOURCE.recording_id,
        "events",
        {
            "operator_id": "operator-0072-m5",
            "expected_revision": event_update.draft.revision,
            "coverage": {"kind": "full_recording"},
        },
    )
    event_reference_id = event_completed.state.selected_completed_revision_id
    assert event_reference_id is not None

    visible_manifest, visible_content = _visible_revision(
        "generated-visible-cards-0072-m5", outcomes
    )
    revision_store.publish(visible_manifest, visible_content)
    visible_reference = service.create_reference(
        SOURCE.recording_id,
        "visible_cards",
        {"operator_id": "operator-0072-m5", "source_revision_id": visible_manifest.revision_id},
    )
    visible_revision = visible_reference.draft.revision
    for outcome in outcomes:
        if outcome["status"] == "failed":
            operation = {"operation": "set_frame_unusable", "item_id": outcome["event_id"]}
        else:
            corrected = deepcopy(outcome)
            corrected["card_scene"] = _pose_envelope(
                reviewed_scenes[str(outcome["event_id"]).removeprefix("event-")][1],
                calibration,
                initialized_scene=reviewed_scenes[str(outcome["event_id"]).removeprefix("event-")][
                    0
                ],
            )
            operation = {
                "operation": "set_frame_review",
                "item_id": outcome["event_id"],
                "item": corrected,
            }
        updated = service.update_draft(
            SOURCE.recording_id,
            "visible_cards",
            {
                "operator_id": "operator-0072-m5",
                "expected_revision": visible_revision,
                "operations": [operation],
            },
        )
        visible_revision = updated.draft.revision
        if outcome["status"] != "failed":
            accepted = service.update_draft(
                SOURCE.recording_id,
                "visible_cards",
                {
                    "operator_id": "operator-0072-m5",
                    "expected_revision": visible_revision,
                    "operations": [
                        {
                            "operation": "accept_frame_suggestions",
                            "item_id": outcome["event_id"],
                        }
                    ],
                },
            )
            visible_revision = accepted.draft.revision

    completed = service.complete_reference(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-0072-m5",
            "expected_revision": visible_revision,
            "coverage": {
                "kind": "visible_frames",
                "frames": [
                    {
                        "frame_identity": outcome["frame_identity"],
                        "decision": "unusable" if outcome["status"] == "failed" else "cards",
                    }
                    for outcome in outcomes
                ],
            },
        },
    )
    completed_revision_id = completed.state.selected_completed_revision_id
    assert completed_revision_id is not None
    completed_revision = revision_store.require(completed_revision_id)
    completed_outcomes = completed_revision.content.to_mapping()["outcomes"]
    assert all(
        outcome.get("card_scene", {}).get("derived_region_receipt")
        for outcome in completed_outcomes
        if outcome["status"] == "detected"
    )

    dataset = materialize_pipeline_dataset(
        revision_store,
        PipelineDatasetRequest(
            task="visible_cards",
            reference_revision_id=completed_revision_id,
            selected_input_revision_ids=(event_reference_id,),
            source_groups=(
                PipelineDatasetSourceGroup(
                    recording_id=SOURCE.recording_id,
                    source_asset_id="source-0072-m5",
                    source_sha256=DIGEST,
                    group_keys=(("session_id", "session-0072-m5"),),
                    source_permission="training_and_evaluation",
                    allowed_uses=("train", "validation"),
                ),
            ),
            policies={"frame": {"policy_id": "exact-event/v1"}},
            partition="train",
            visible_card_ignore_policy="mask_pixels",
        ),
        tmp_path / "dataset",
    )
    assert dataset["target_count"] == 11
    assert dataset["manifest"]["lineage"]["reference"]["input_revision_ids"] == [
        visible_manifest.revision_id
    ]
    assert dataset["manifest"]["lineage"]["inputs"][0]["revision_id"] == event_reference_id
    assert (tmp_path / "dataset" / "dataset-manifest.json").is_file()

    report = {
        "schema_version": "pose-based-review-loop-verification/v1",
        "calibration": {
            "runtime_ms": calibration_runtime_ms,
            "candidate_yield": calibration_run.diagnostics["candidate_yield"],
            "rejections": calibration_run.diagnostics["rejections"],
            "revision_id": calibration.calibration_revision_id,
            "digest": calibration.calibration_digest,
        },
        "frames": frame_metrics,
        "lineage": {
            "generated_visible_revision_id": visible_manifest.revision_id,
            "completed_visible_reference_id": completed_revision_id,
            "event_reference_id": event_reference_id,
            "dataset_id": dataset["dataset_id"],
            "dataset_digest": dataset["dataset_digest"],
        },
    }
    report_path = tmp_path / "pose-review-loop-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    restored_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert restored_report["calibration"]["runtime_ms"] >= 0
    assert restored_report["calibration"]["candidate_yield"]["accepted_count"] >= 6
    assert restored_report["calibration"]["rejections"]["calibration-duplicate"] == (
        "overlaps_prediction"
    )
    assert sum(item["accepted_pose_count"] for item in frame_metrics) == 11
    assert sum(item["moved_cards"] for item in frame_metrics) == 2
    assert sum(item["rotations"] for item in frame_metrics) == 2
    assert sum(item["reorder_actions"] for item in frame_metrics) == 2
    assert sum(item["additions"] for item in frame_metrics) == 1
    assert sum(item["removals"] for item in frame_metrics) == 1
    assert sum(item["ignore_regions"] for item in frame_metrics) == 0
    assert sum(item["unusable"] for item in frame_metrics) == 1
