from __future__ import annotations

import json
from pathlib import Path

from doko_operations.rfdetr_segmentation_materialization import (
    validate_rfdetr_coco_annotations,
)
from doko_operations.synthetic_visible_region_recording_synthesis import (
    _select_table_geometry_references,
    _synthesis_candidates,
    build_synthetic_visible_region_all_recordings,
    build_synthetic_visible_region_recording_discovery,
)


def test_discovery_covers_all_recordings_and_preserves_holdout_policy() -> None:
    repository = Path(__file__).parents[2]
    manifest = build_synthetic_visible_region_recording_discovery(repository)

    assert manifest["inventory"]["recording_count"] == 24
    assert manifest["inventory"]["candidate_count"] == 235
    assert manifest["inventory"]["selected_train_scene_count"] == 38
    assert manifest["outputs"] is None
    assert all(
        recording["synthesis_policy"] == "discovery_only"
        for recording in manifest["recordings"]
        if recording["source_split"] in {"validation", "sealed_test"}
    )


def test_all_train_candidate_policy_exposes_the_full_geometry_pool() -> None:
    repository = Path(__file__).parents[2]
    discovery = build_synthetic_visible_region_recording_discovery(repository)

    candidates = _synthesis_candidates(discovery, "all_train_candidates")

    assert len(candidates) == 169
    assert {recording["source_split"] for recording, _ in candidates} == {"train"}
    assert {candidate["source_split"] for _, candidate in candidates} == {"train"}
    assert {candidate["card_count"] for _, candidate in candidates} == {1, 2, 3}


def test_four_card_discovery_selects_three_train_geometry_frames_per_table() -> None:
    repository = Path(__file__).parents[2]
    discovery = build_synthetic_visible_region_recording_discovery(
        repository, max_card_count=4
    )

    references = _select_table_geometry_references(discovery, 3)

    assert len(references) == 14
    assert all(len(items) == 3 for items in references.values())
    assert all(
        len({item["event_id"] for item in items}) == 3 for items in references.values()
    )
    assert any(
        candidate["card_count"] == 4
        for candidate in discovery["candidates"]
        if candidate["source_split"] == "train"
    )


def test_synthesis_is_train_only_and_emits_valid_coco(tmp_path: Path) -> None:
    repository = Path(__file__).parents[2]
    manifest = build_synthetic_visible_region_all_recordings(
        repository,
        output_directory=tmp_path / "all-recordings",
    )

    assert manifest["inventory"]["synthesized_recording_count"] == 15
    assert manifest["inventory"]["synthesized_scene_count"] == 38
    assert manifest["inventory"]["synthesized_scene_counts_by_card_count"] == {
        "1": 14,
        "2": 12,
        "3": 12,
    }
    assert all(
        scene["recording_id"].startswith("cardeventnet-IMG_")
        for scene in manifest["scenes"]
    )
    assert all(
        recording["source_split"] == "train"
        for recording in manifest["recordings"]
        if any(scene["recording_id"] == recording["recording_id"] for scene in manifest["scenes"])
    )

    coco_path = tmp_path / "all-recordings" / "_annotations.coco.json"
    coco = json.loads(coco_path.read_text(encoding="utf-8"))
    validate_rfdetr_coco_annotations(coco)
    assert len(coco["images"]) == 38
    assert len(coco["annotations"]) == 74
    assert len({image["id"] for image in coco["images"]}) == 38
    assert {image["trainer_partition"] for image in coco["images"]} == {"train"}
