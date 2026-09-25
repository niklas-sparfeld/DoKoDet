from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from doko_operations.card_plane_geometry import (
    CardPose,
    CardStackingOrder,
    ReviewedCardScene,
    derive_visible_masks,
    mask_bbox,
    project_rounded_card,
    rasterize_polygon,
)
from doko_operations.rfdetr_pose_derived_materialization import (
    RfdetrPoseDerivedMaterializationError,
    _checked_frame_digest,
    _coco_rle_annotation,
    _validate_coco_rle,
    load_rfdetr_pose_derived_materialization,
    materialize_rfdetr_pose_derived_dataset,
)
from doko_operations.rfdetr_segmentation_campaign import sha256_json


def _scene(
    poses: list[CardPose], stacking_order: list[str], *, width: int = 100, height: int = 100
) -> ReviewedCardScene:
    return ReviewedCardScene.create(
        source_frame_id="frame-1",
        source_frame_width=width,
        source_frame_height=height,
        calibration_revision_id="calibration-1",
        calibration_digest="a" * 64,
        poses=poses,
        stacking_order=CardStackingOrder(
            card_ids=tuple(stacking_order), uncertain_edges=(), contradictions=()
        ),
    )


def _pose(card_id: str, center: tuple[float, float]) -> CardPose:
    return CardPose(
        card_id=card_id,
        center=center,
        rotation_degrees=0.0,
        source_suggestion_id=None,
        fit_diagnostics_digest=None,
    )


def test_rounded_pose_outline_has_curved_corners() -> None:
    pose = _pose("card-1", (0.5, 0.5))
    calibration = {
        "table_to_image": [[20.0, 0.0, 10.0], [0.0, 20.0, 10.0], [0.0, 0.0, 1.0]],
        "card_short_size": 1.0,
        "card_long_size": 1.5,
    }
    projected = project_rounded_card(
        np.asarray(calibration["table_to_image"]),
        pose.center,
        pose.rotation_degrees,
        calibration["card_short_size"],
        calibration["card_long_size"],
    )
    mask = rasterize_polygon(projected, 100, 100)
    _x, _y, width, height = mask_bbox(mask)
    assert width > 0 and height > 0
    assert int(np.count_nonzero(mask)) < width * height


def test_three_card_front_to_back_order_subtracts_each_front_card() -> None:
    first = np.zeros((12, 16), dtype=np.uint8)
    second = np.zeros_like(first)
    third = np.zeros_like(first)
    first[2:10, 1:7] = 255
    second[2:10, 5:11] = 255
    third[2:10, 9:15] = 255
    visible = derive_visible_masks([first, second, third], [0, 1, 2])
    assert visible[0][5, 5] == 255
    assert visible[1][5, 5] == 0
    assert visible[1][5, 8] == 255
    assert visible[2][5, 9] == 0
    assert visible[2][5, 12] == 255


def test_occlusion_preserves_disconnected_and_enclosed_visible_components() -> None:
    back = np.full((15, 15), 255, dtype=np.uint8)
    front = np.zeros_like(back)
    front[:, 6:9] = 255
    split = derive_visible_masks([front, back], [0, 1])[1]
    component_count, _ = cv2.connectedComponents((split > 0).astype(np.uint8))
    assert component_count - 1 == 2

    enclosed_front = np.zeros_like(back)
    enclosed_front[5:10, 5:10] = 255
    ring = derive_visible_masks([enclosed_front, back], [0, 1])[1]
    assert ring[7, 7] == 0
    assert ring[2, 2] == 255
    assert np.count_nonzero(ring) == 200


def test_rasterizer_returns_an_empty_mask_when_card_is_outside_frame() -> None:
    clipped = rasterize_polygon(
        np.asarray([[-4, -4], [4, -4], [4, 4], [-4, 4]], dtype=np.float64),
        100,
        100,
    )
    assert mask_bbox(clipped) == [0, 0, 5, 5]
    mask = rasterize_polygon(
        np.asarray([[120, 120], [140, 120], [140, 140], [120, 140]], dtype=np.float64),
        100,
        100,
    )
    assert not np.any(mask)


def test_coco_rle_round_trip_keeps_mask_pixels_and_lineage() -> None:
    mask = np.zeros((10, 12), dtype=np.uint8)
    mask[1:4, 2:6] = 255
    mask[7:9, 9:11] = 255
    pose = _pose("pose-1", (0.0, 0.0))
    scene = _scene([pose], [pose.card_id], width=12, height=10)
    entry = {
        "m0_manifest_digest": "b" * 64,
        "recording_id": "recording-1",
        "frame_id": "frame-1",
        "run_id": "run-1",
        "proposal_revision_id": "proposal-revision-1",
        "proposal_revision_sha256": "c" * 64,
        "proposal_content_sha256": "d" * 64,
        "calibration_revision_id": "calibration-1",
        "calibration_digest": "a" * 64,
        "source_frame_digest": "e" * 64,
        "source_group": {
            "partition": "train",
            "group_key": "f" * 64,
            "source_sha256": "1" * 64,
        },
    }
    coco = {
        "info": {},
        "licenses": [],
        "images": [{"id": 1, "width": 12, "height": 10}],
        "annotations": [
            _coco_rle_annotation(
                annotation_id=1,
                image_id=1,
                entry=entry,
                pose_id=pose.card_id,
                pose_index=0,
                mask=mask,
                box=mask_bbox(mask),
                scene=scene,
            )
        ],
        "categories": [{"id": 1, "name": "visible_card", "supercategory": "card"}],
    }
    _validate_coco_rle(coco)
    damaged = json.loads(json.dumps(coco))
    damaged["annotations"][0]["bbox"][0] += 1
    with pytest.raises(RfdetrPoseDerivedMaterializationError, match="tight"):
        _validate_coco_rle(damaged)


def test_changed_source_frame_bytes_are_rejected() -> None:
    digest = hashlib.sha256(b"expected frame").hexdigest()
    with pytest.raises(RfdetrPoseDerivedMaterializationError, match="digest differs"):
        _checked_frame_digest(
            b"changed frame", {"frame_id": "frame-1", "source_frame_digest": digest}
        )


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _make_minimal_campaign(root: Path) -> tuple[Path, bytes]:
    frame = np.zeros((96, 96, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", frame)
    assert ok
    image_bytes = encoded.tobytes()
    source_video_bytes = b"frozen video input"
    source_video_digest = hashlib.sha256(source_video_bytes).hexdigest()
    frame_digest = hashlib.sha256(image_bytes).hexdigest()
    source_video_path = root / "data/intake/video.mov"
    source_video_path.parent.mkdir(parents=True, exist_ok=True)
    source_video_path.write_bytes(source_video_bytes)
    group = {
        "group_key": "a" * 64,
        "partition": "train",
        "recording_id": "recording-1",
        "session_id": "session-1",
        "source_asset_id": "asset-1",
        "video_id": "video-1",
        "source_sha256": source_video_digest,
        "table_setup": "setup-1",
    }
    pose = _pose("pose-1", (1.1, 1.1))
    calibration = {
        "recording_id": "recording-1",
        "calibration_revision_id": "calibration-1",
        "calibration_digest": "b" * 64,
        "table_to_image": [[32.0, 0.0, 0.0], [0.0, 32.0, 0.0], [0.0, 0.0, 1.0]],
        "card_short_size": 1.0,
        "card_long_size": 1.5,
    }
    from doko_operations.card_plane_geometry import CardStackingOrder

    scene = ReviewedCardScene.create(
        source_frame_id="frame-1",
        source_frame_width=96,
        source_frame_height=96,
        calibration_revision_id="calibration-1",
        calibration_digest=calibration["calibration_digest"],
        poses=[pose],
        stacking_order=CardStackingOrder((pose.card_id,), (), ()),
    ).to_mapping()
    proposal = {
        "source_frame_id": "frame-1",
        "source_frame_digest": frame_digest,
        "calibration_revision_id": "calibration-1",
        "calibration_digest": calibration["calibration_digest"],
        "status": "supported",
        "initialized_scene": scene,
        "detector_revision_id": "detector-revision-1",
    }
    frame_identity = {
        "source_video_sha256": source_video_digest,
        "requested_time_us": 10,
        "frame_index": 1,
        "presentation_timestamp_us": 10,
        "width": 96,
        "height": 96,
        "image_sha256": frame_digest,
    }
    detector_content = {"outcomes": [{"event_id": "frame-1", "frame_identity": frame_identity}]}
    detector_content_digest = sha256_json(detector_content)
    proposal["detector_revision_digest"] = detector_content_digest
    proposal_content = {
        "calibration": calibration,
        "calibration_revision_id": "calibration-1",
        "calibration_digest": calibration["calibration_digest"],
        "detector_revision_id": "detector-revision-1",
        "detector_revision_digest": "d" * 64,
        "frames": [
            {"frame_id": "frame-1", "source_frame_digest": frame_digest, "proposal": proposal}
        ],
    }
    proposal_content_digest = sha256_json(proposal_content)
    proposal_manifest = {
        "revision_id": "proposal-revision-1",
        "recording_id": "recording-1",
        "content_sha256": proposal_content_digest,
    }
    proposal_dir = root / "data/operations/pipeline/revisions/proposal-revision-1"
    _write_json(proposal_dir / "content.json", proposal_content)
    _write_json(proposal_dir / "manifest.json", proposal_manifest)
    proposal_manifest_digest = hashlib.sha256(
        (proposal_dir / "manifest.json").read_bytes()
    ).hexdigest()

    detector_manifest = {
        "revision_id": "detector-revision-1",
        "recording_id": "recording-1",
        "content_sha256": detector_content_digest,
    }
    detector_dir = root / "data/operations/pipeline/revisions/detector-revision-1"
    _write_json(detector_dir / "content.json", detector_content)
    _write_json(detector_dir / "manifest.json", detector_manifest)

    scene_entry = {
        "recording_id": "recording-1",
        "frame_id": "frame-1",
        "run_id": "run-1",
        "source_frame_digest": frame_digest,
        "proposal_revision_id": "proposal-revision-1",
        "proposal_revision_sha256": proposal_manifest_digest,
        "proposal_content_sha256": proposal_content_digest,
        "visible_card_revision_id": "detector-revision-1",
        "visible_card_revision_digest": detector_content_digest,
        "calibration_revision_id": "calibration-1",
        "calibration_digest": calibration["calibration_digest"],
        "scene_digest": scene["scene_digest"],
        "pose_ids": [pose.card_id],
        "source_group": group,
    }
    manifest = {
        "schema_version": "rfdetr-pose-derived-campaign-manifest/v1",
        "campaign_id": "0084-m0-rfdetr-pose-derived-visible-cards",
        "freeze_state": "frozen",
        "mask_policy": {
            "encoding": "COCO_RLE",
            "minimum_visible_pixels": 10,
            "minimum_tight_box_width_pixels": 4,
            "minimum_tight_box_height_pixels": 4,
            "mask_minimum_gate": {
                "minimum_frames": 1,
                "minimum_masks": 1,
                "minimum_source_groups": 1,
            },
        },
        "eligible_scenes": [scene_entry],
        "excluded_scenes": [],
        "verified_source_videos": [
            {
                "recording_id": "recording-1",
                "relative_path": "data/intake/video.mov",
                "sha256": source_video_digest,
                "byte_length": len(source_video_bytes),
                "bytes_verified": True,
            }
        ],
    }
    manifest["manifest_digest"] = sha256_json(manifest)
    manifest_path = root / "data/operations/m0.json"
    _write_json(manifest_path, manifest)
    return manifest_path, image_bytes


def test_cold_and_warm_materialization_have_the_same_digest(tmp_path: Path) -> None:
    manifest_path, image_bytes = _make_minimal_campaign(tmp_path)
    output_path = tmp_path / "data/operations/view"
    def extractor(_video: Path, _identity: dict) -> bytes:
        return image_bytes
    cold = materialize_rfdetr_pose_derived_dataset(
        manifest_path,
        repository_root=tmp_path,
        output_root=output_path,
        frame_extractor=extractor,
    )
    warm = materialize_rfdetr_pose_derived_dataset(
        manifest_path,
        repository_root=tmp_path,
        output_root=output_path,
        frame_extractor=extractor,
    )
    assert cold.materialization_digest == warm.materialization_digest
    assert cold.image_count == 1
    assert cold.annotation_count == 1
    assert load_rfdetr_pose_derived_materialization(output_path)["materialization_digest"] == (
        cold.materialization_digest
    )


def test_materializer_rejects_changed_frame_bytes(tmp_path: Path) -> None:
    manifest_path, _image_bytes = _make_minimal_campaign(tmp_path)
    with pytest.raises(RfdetrPoseDerivedMaterializationError, match="frame digest differs"):
        materialize_rfdetr_pose_derived_dataset(
            manifest_path,
            repository_root=tmp_path,
            output_root=tmp_path / "data/operations/changed",
            frame_extractor=lambda _video, _identity: b"not the frozen frame",
        )
