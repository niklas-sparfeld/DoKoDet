from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from doko_operations.rfdetr_pose_derived_campaign import (
    RfdetrPoseDerivedCampaignError,
    build_rfdetr_pose_derived_manifest,
    write_rfdetr_pose_derived_manifest,
)
from doko_operations.rfdetr_segmentation_campaign import sha256_json


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _campaign_inputs(root: Path, *, uncertain: bool = False) -> tuple[Path, Path]:
    operations = root / "data" / "operations"
    video_bytes = b"source-video"
    source_sha = hashlib.sha256(video_bytes).hexdigest()
    train_video = "data/intake/recordings/recording-train/video.mov"
    validation_video = "data/intake/recordings/recording-validation/video.mov"
    for relative_path in (train_video, validation_video):
        video_path = root / relative_path
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(video_bytes)
    source_core = {
        "schema_version": "rfdetr-visible-card-detector-manifest/v1",
        "freeze_state": "frozen",
        "manifest_digest": "",
        "source_groups": [
            {
                "recording_id": "recording-train",
                "partition": "train",
                "group_key": "group-train",
                "source_sha256": source_sha,
            },
            {
                "recording_id": "recording-validation",
                "partition": "validation",
                "group_key": "group-validation",
                "source_sha256": hashlib.sha256(b"validation-video").hexdigest(),
            },
        ],
        "samples": [
            {"event_id": "frame-duplicate", "split": "train"},
        ],
        "recordings": [
            {
                "recording_id": "recording-train",
                "allowed_uses": ["train"],
                "retention_state": "active",
                "source_video_path": train_video,
                "source_byte_length": len(video_bytes),
            },
            {
                "recording_id": "recording-validation",
                "allowed_uses": ["validation"],
                "retention_state": "active",
                "source_video_path": validation_video,
                "source_byte_length": len(video_bytes),
            },
        ],
        "split": {"train": {"retained_frames": 10}},
        "recipe": {"validation": {"metrics": ["mask_ap_50_95", "recall"]}},
    }
    source_core.pop("manifest_digest")
    source_core["recipe_sha256"] = sha256_json(source_core["recipe"])
    source = {**source_core, "manifest_digest": sha256_json(source_core)}
    source_path = operations / "0068-manifest.json"
    _write_json(source_path, source)

    for run_id, recording_id, frame_id in (
        ("proposal-run-train", "recording-train", "frame-eligible"),
        ("proposal-run-validation", "recording-validation", "frame-heldout"),
    ):
        revision_id = f"card-scene-proposals-{run_id}"
        detector_revision_id = f"visible-cards-{run_id}"
        detector_digest = hashlib.sha256(detector_revision_id.encode()).hexdigest()
        calibration_id = f"calibration-{run_id}"
        calibration_digest = hashlib.sha256(calibration_id.encode()).hexdigest()
        calibration = {
            "calibration_revision_id": calibration_id,
            "calibration_digest": calibration_digest,
            "recording_id": recording_id,
            "table_to_image": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "card_short_size": 1,
            "card_long_size": 2,
        }
        source_frame_digest = hashlib.sha256(frame_id.encode()).hexdigest()
        content = {
            "calibration": calibration,
            "calibration_digest": calibration_digest,
            "calibration_revision_id": calibration_id,
            "detector_revision_digest": detector_digest,
            "detector_revision_id": detector_revision_id,
            "frames": [
                {
                    "frame_id": frame_id,
                    "source_frame_digest": source_frame_digest,
                    "status": "supported",
                }
            ],
            "schema_version": "proposed-card-scene-data/v1",
        }
        revision = {
            "revision_id": revision_id,
            "recording_id": recording_id,
            "content_sha256": sha256_json(content),
            "producer": {"run_id": run_id},
            "source": {"video_sha256": source_sha},
            "coverage": {
                "detector_revision_id": detector_revision_id,
                "detector_revision_digest": detector_digest,
                "calibration_revision_id": calibration_id,
                "calibration_digest": calibration_digest,
            },
        }
        _write_json(operations / "pipeline" / "revisions" / revision_id / "manifest.json", revision)
        _write_json(operations / "pipeline" / "revisions" / revision_id / "content.json", content)
        _write_json(
            operations / "pipeline" / "revisions" / detector_revision_id / "manifest.json",
            {
                "content_sha256": detector_digest,
                "recording_id": recording_id,
                "producer": {
                    "model_id": "local-rfdetr-segmentation.test",
                    "run_id": f"visible-run-{run_id}",
                },
            },
        )
        _write_json(
            operations / "pipeline" / "runs" / run_id / "request.json",
            {
                "run_id": run_id,
                "source": {
                    "recording_id": recording_id,
                    "video_sha256": source_sha,
                    "relative_path": train_video
                    if recording_id == "recording-train"
                    else validation_video,
                    "byte_length": len(video_bytes),
                },
                "input_revision_ids": [detector_revision_id],
            },
        )
        _write_json(
            operations / "pipeline" / "runs" / run_id / "state.json",
            {
                "run_id": run_id,
                "status": "complete",
                "created_at": "2026-09-25T12:00:00Z",
                "completed_at": "2026-09-25T12:01:00Z",
                "output_revision_ids": [revision_id],
            },
        )
        pose_id = f"pose-{frame_id}"
        order = {
            "card_ids": [pose_id],
            "contradictions": [],
            "uncertain_edges": [[pose_id, "pose-other"]] if uncertain else [],
        }
        _write_json(
            operations / "pipeline" / "runs" / run_id / "items" / f"{frame_id}.json",
            {
                "item_id": frame_id,
                "status": "succeeded",
                "result": {
                    "proposal": {
                        "status": "supported",
                        "source_frame_id": frame_id,
                        "source_frame_digest": source_frame_digest,
                        "initializer_recipe_version": "fixed-card-pose-grid-search/v3",
                        "detector_revision_id": detector_revision_id,
                        "detector_revision_digest": detector_digest,
                        "calibration_revision_id": calibration_id,
                        "calibration_digest": calibration_digest,
                        "initialized_scene": {
                            "scene_digest": hashlib.sha256(
                                (frame_id + "scene").encode()
                            ).hexdigest(),
                            "calibration_revision_id": calibration_id,
                            "calibration_digest": calibration_digest,
                            "poses": [{"card_id": pose_id}],
                            "stacking_order": order,
                        },
                        "fit_diagnostics": {
                            "diagnostics": {
                                "candidate_count": 1,
                                "initialized_count": 1,
                                "recipe_digest": hashlib.sha256(b"pose-recipe").hexdigest(),
                                "failed_suggestion_ids": [],
                                "low_confidence_suggestion_ids": [],
                            },
                            "fit_diagnostics": [{"card_id": pose_id, "accepted": True}],
                        },
                    }
                },
            },
        )
    return source_path, operations


def test_manifest_is_deterministic_and_excludes_heldout_and_reviewed_frames(tmp_path: Path) -> None:
    source, operations = _campaign_inputs(tmp_path)
    manifest = build_rfdetr_pose_derived_manifest(
        tmp_path,
        source_manifest_path=source,
        operations_root=operations,
        proposal_run_ids=["proposal-run-validation", "proposal-run-train"],
        minimum_frames=1,
        minimum_groups=1,
        minimum_poses=1,
    )
    repeated = build_rfdetr_pose_derived_manifest(
        tmp_path,
        source_manifest_path=source,
        operations_root=operations,
        proposal_run_ids=["proposal-run-train", "proposal-run-validation"],
        minimum_frames=1,
        minimum_groups=1,
        minimum_poses=1,
    )

    assert repeated["manifest_digest"] == manifest["manifest_digest"]
    assert manifest["freeze_state"] == "frozen"
    assert [scene["frame_id"] for scene in manifest["eligible_scenes"]] == ["frame-eligible"]
    reasons = {
        reason for exclusion in manifest["excluded_scenes"] for reason in exclusion["reasons"]
    }
    assert "source_group_not_in_0068_training_partition" in reasons

    destination = tmp_path / "frozen.json"
    write_rfdetr_pose_derived_manifest(destination, manifest)
    write_rfdetr_pose_derived_manifest(destination, manifest)
    with pytest.raises(RfdetrPoseDerivedCampaignError, match="refusing to replace"):
        write_rfdetr_pose_derived_manifest(destination, {**manifest, "manifest_digest": "changed"})


def test_manifest_excludes_ambiguous_order_and_records_duplicate_receipt(tmp_path: Path) -> None:
    source, operations = _campaign_inputs(tmp_path, uncertain=True)
    # Add a second item that matches a reviewed 0068 training frame.
    run_id = "proposal-run-train"
    run_dir = operations / "pipeline" / "runs" / run_id
    item = json.loads((run_dir / "items" / "frame-eligible.json").read_text())
    item["item_id"] = "frame-duplicate"
    item["result"]["proposal"]["source_frame_id"] = "frame-duplicate"
    duplicate_digest = hashlib.sha256(b"frame-duplicate").hexdigest()
    item["result"]["proposal"]["source_frame_digest"] = duplicate_digest
    _write_json(run_dir / "items" / "frame-duplicate.json", item)
    revision_id = "card-scene-proposals-proposal-run-train"
    content_path = operations / "pipeline" / "revisions" / revision_id / "content.json"
    content = json.loads(content_path.read_text())
    content["frames"].append(
        {
            "frame_id": "frame-duplicate",
            "source_frame_digest": duplicate_digest,
            "status": "supported",
        }
    )
    _write_json(content_path, content)
    revision_path = operations / "pipeline" / "revisions" / revision_id / "manifest.json"
    revision = json.loads(revision_path.read_text())
    revision["content_sha256"] = sha256_json(content)
    _write_json(revision_path, revision)
    manifest = build_rfdetr_pose_derived_manifest(
        tmp_path,
        source_manifest_path=source,
        operations_root=operations,
        proposal_run_ids=[run_id],
        minimum_frames=1,
        minimum_groups=1,
        minimum_poses=1,
    )

    assert manifest["freeze_state"] == "blocked"
    assert not manifest["eligible_scenes"]
    reasons = {
        reason for exclusion in manifest["excluded_scenes"] for reason in exclusion["reasons"]
    }
    assert "unresolved_overlapping_card_order" in reasons
    assert "duplicate_of_0068_reviewed_training_frame" in reasons
