from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import doko_operations.reviewed_rfdetr_detector_campaign as reviewed_campaign
from doko_operations.rfdetr_card_cluster_materialization import (
    RfdetrCardClusterMaterializationError,
    load_rfdetr_card_cluster_materialization,
    materialize_rfdetr_card_cluster_dataset,
)
from doko_operations.rfdetr_segmentation_campaign import sha256_json


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _manifest_fixture(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, bytes]]:
    monkeypatch.setattr(reviewed_campaign, "REQUIRED_SEALED_TEST_GROUPS", 1)
    checkpoint = b"checkpoint"
    source_frames = {
        "train": b"train-frame",
        "validation": b"validation-frame",
        "sealed_test": b"sealed-frame",
    }
    operations = root / "data" / "operations"
    recordings_root = root / "data" / "intake" / "recordings"
    samples: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    recordings: list[dict[str, Any]] = []
    source_groups: list[dict[str, Any]] = []
    partition_recordings = {
        "train": "recording-train",
        "validation": "recording-validation",
        "sealed_test": "recording-sealed",
    }
    target_polygons = {
        "train": [
            (100, 100, 300, 300),
            (350, 120, 550, 320),
            (600, 100, 800, 300),
        ],
        "validation": [(10, 10, 200, 200)],
        "sealed_test": [(400, 400, 600, 600)],
    }
    for index, (split, recording_id) in enumerate(partition_recordings.items()):
        source_bytes = f"video-{split}".encode()
        source_digest = _digest_bytes(source_bytes)
        bundle = recordings_root / recording_id
        bundle.mkdir(parents=True)
        (bundle / "video.mp4").write_bytes(source_bytes)
        manifest_path = bundle / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "repository-bundle/v1",
                    "state": "complete",
                    "recording_id": recording_id,
                    "session_id": f"session-{split}",
                    "source_asset_id": f"asset-{split}",
                    "video_id": f"video-{split}",
                    "source_sha256": source_digest,
                    "files": {
                        "video": {"relative_path": "video.mp4", "byte_length": len(source_bytes)}
                    },
                }
            ),
            encoding="utf-8",
        )
        (bundle / "source-record.json").write_text(
            json.dumps(
                {
                    "recording_id": recording_id,
                    "session_id": f"session-{split}",
                    "source_asset_id": f"asset-{split}",
                    "video_id": f"video-{split}",
                    "table_setup": f"setup-{split}",
                    "sha256": source_digest,
                    "allowed_uses": ["train", "validation", "evaluation"],
                    "source_permission": "project_use",
                    "retention_state": "active",
                }
            ),
            encoding="utf-8",
        )
        frame_bytes = source_frames[split]
        frame_digest = _digest_bytes(frame_bytes)
        frame = {
            "frame_index": index,
            "image_sha256": frame_digest,
            "source_video_sha256": source_digest,
            "width": 1000,
            "height": 1000,
        }
        event_id = f"event-{split}"
        targets = []
        for card_index, (x_min, y_min, x_max, y_max) in enumerate(target_polygons[split]):
            targets.append(
                {
                    "card_id": f"{event_id}:card-{card_index}",
                    "side": "face_up",
                    "geometry": {
                        "kind": "reviewed-visible-region/v1",
                        "visible_region": {
                            "polygons": [
                                [
                                    {"x": x_min, "y": y_min},
                                    {"x": x_max, "y": y_min},
                                    {"x": x_max, "y": y_max},
                                    {"x": x_min, "y": y_max},
                                ]
                            ]
                        },
                    },
                    "normalization": {
                        "policy_id": "full-frame-0-1000/v1",
                        "width": 1000,
                        "height": 1000,
                    },
                }
            )
        sample = {
            "recording_id": recording_id,
            "split": split,
            "session_id": f"session-{split}",
            "table_setup": f"setup-{split}",
            "source_asset_id": f"asset-{split}",
            "source_sha256": source_digest,
            "reference_revision_id": f"revision-{split}",
            "event_id": event_id,
            "item_id": event_id,
            "frame_identity": frame,
            "targets": targets,
        }
        group_core = {
            "recording_id": recording_id,
            "session_id": f"session-{split}",
            "source_asset_id": f"asset-{split}",
            "video_id": f"video-{split}",
            "source_sha256": source_digest,
            "table_setup": f"setup-{split}",
        }
        group = {**group_core, "partition": split, "group_key": sha256_json(group_core)}
        sample["source_group"] = group_core
        sample["source_group_key"] = group["group_key"]
        samples.append(sample)
        references.append(
            {"recording_id": recording_id, "origin": "corrected", "samples": [sample]}
        )
        recordings.append(
            {
                "recording_id": recording_id,
                "split": split,
                "session_id": f"session-{split}",
                "source_asset_id": f"asset-{split}",
                "video_id": f"video-{split}",
                "table_setup": f"setup-{split}",
                "source_sha256": source_digest,
                "source_byte_length": len(source_bytes),
                "source_video_path": f"data/intake/recordings/{recording_id}/video.mp4",
            }
        )
        source_groups.append(group)

    recipe = {
        "model": {"class": "RFDETRSegMedium", "resolution": [432, 432]},
        "package": {"name": "rfdetr", "version": "1.9.4"},
        "pretrained_checkpoint": {"sha256": _digest_bytes(checkpoint)},
        "data_contract": {"test_partition": "sealed_test"},
    }
    split = {
        partition: {"recording_ids": [recording_id]}
        for partition, recording_id in partition_recordings.items()
    }
    core: dict[str, Any] = {
        "schema_version": "rfdetr-visible-card-detector-manifest/v1",
        "campaign_id": "0068-m0-reviewed-rfdetr-local-visible-card-detector",
        "milestone": "M0",
        "read_only": True,
        "freeze_state": "frozen",
        "selection": {
            "strategy": "selected_completed_corrected_visible_card_references/v1",
            "selected_recording_ids": sorted(partition_recordings.values()),
            "unavailable_references": [],
        },
        "split": split,
        "recipe": recipe,
        "recipe_sha256": sha256_json(recipe),
        "api_probe": {"status": "available", "gaps": []},
        "source_groups": source_groups,
        "recordings": recordings,
        "references": references,
        "samples": samples,
        "excluded_frames": [
            {
                "recording_id": "recording-sealed",
                "event_id": "excluded-event",
                "split": "sealed_test",
                "reason": "reviewed ignore region",
            }
        ],
        "ineligible_outcomes": [
            {
                "recording_id": "recording-sealed",
                "event_id": "ineligible-event",
                "split": "sealed_test",
                "reason": "reviewed unusable outcome",
            }
        ],
        "inventory": {
            "selected_recording_count": 3,
            "recording_count": 3,
            "completed_corrected_reference_count": 3,
            "reviewed_frame_count": 3,
            "retained_frame_count": 3,
            "excluded_frame_count": 1,
            "ineligible_outcome_count": 1,
            "ignored_region_count": 1,
            "target_count": 5,
            "side_counts": {"face_up": 5, "face_down": 0, "unknown": 0},
        },
        "holdout_registry": {},
        "coverage_gaps": [],
    }
    manifest = {**core, "manifest_digest": sha256_json(core)}
    manifest_path = operations / "rfdetr-visible-card-detector-0068-m0-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(json.dumps(manifest).encode() + b"\n")
    frame_lookup = {
        _digest_bytes(value): value for value in source_frames.values()
    }
    return manifest_path, frame_lookup


def test_materializer_derives_transitive_clusters_and_reproducible_views(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, frame_bytes = _manifest_fixture(tmp_path, monkeypatch)

    def extract(_source: Path, frame: dict[str, Any]) -> bytes:
        return frame_bytes[frame["image_sha256"]]

    first = materialize_rfdetr_card_cluster_dataset(
        manifest_path,
        repository_root=tmp_path,
        output_root=tmp_path / "view-one",
        frame_extractor=extract,
    )
    second = materialize_rfdetr_card_cluster_dataset(
        manifest_path,
        repository_root=tmp_path,
        output_root=tmp_path / "view-two",
        frame_extractor=extract,
    )

    assert first.to_mapping() | {"view_root": "same"} == second.to_mapping() | {"view_root": "same"}
    assert first.image_count == 2
    assert first.annotation_count == 2
    assert first.cluster_count == 2
    assert first.reviewed_card_count == 4
    assert first.excluded_frame_count == 1
    assert first.ineligible_outcome_count == 1
    assert load_rfdetr_card_cluster_materialization(first.view_root)["counts"]["clusters"] == 2

    train = json.loads((first.view_root / "train" / "_annotations.coco.json").read_text())
    assert train["categories"] == [{"id": 1, "name": "card_cluster", "supercategory": "card"}]
    assert len(train["annotations"]) == 1
    assert train["annotations"][0]["member_card_ids"] == [
        "event-train:card-0",
        "event-train:card-1",
        "event-train:card-2",
    ]
    assert train["annotations"][0]["bbox"] == [100, 100, 700, 220]
    lineage = json.loads((first.view_root / "lineage.json").read_text())
    train_lineage = next(
        frame for frame in lineage["frames"] if frame["split"] == "train"
    )
    assert all(card["cluster_id"] == "cluster-0001" for card in train_lineage["source_cards"])

    first_files = sorted(
        (path.relative_to(first.view_root).as_posix(), _digest_bytes(path.read_bytes()))
        for path in first.view_root.rglob("*")
        if path.is_file()
    )
    second_files = sorted(
        (path.relative_to(second.view_root).as_posix(), _digest_bytes(path.read_bytes()))
        for path in second.view_root.rglob("*")
        if path.is_file()
    )
    assert first_files == second_files


def test_materializer_rejects_changed_frame_and_preserves_sealed_exclusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, frame_bytes = _manifest_fixture(tmp_path, monkeypatch)

    def extract(_source: Path, frame: dict[str, Any]) -> bytes:
        return frame_bytes[frame["image_sha256"]] + b"changed"

    with pytest.raises(RfdetrCardClusterMaterializationError, match="recorded frame digest"):
        materialize_rfdetr_card_cluster_dataset(
            manifest_path,
            repository_root=tmp_path,
            output_root=tmp_path / "view",
            frame_extractor=extract,
        )

    def valid_extract(_source: Path, frame: dict[str, Any]) -> bytes:
        return frame_bytes[frame["image_sha256"]]

    result = materialize_rfdetr_card_cluster_dataset(
        manifest_path,
        repository_root=tmp_path,
        output_root=tmp_path / "view-valid",
        frame_extractor=valid_extract,
    )
    exclusions = json.loads((result.view_root / "exclusions.json").read_text())
    assert len(exclusions["sealed_test_samples"]) == 1
    assert exclusions["excluded_frames"][0]["reason"] == "reviewed ignore region"
    assert exclusions["ineligible_outcomes"][0]["reason"] == "reviewed unusable outcome"
