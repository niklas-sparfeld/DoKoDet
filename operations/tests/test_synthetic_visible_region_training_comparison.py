from __future__ import annotations

import json
from pathlib import Path

from table_evidence_analyzer.rfdetr_segmentation_training import _load_materialization_view

from doko_operations.synthetic_visible_region_training_comparison import (
    build_synthetic_visible_region_m4_view,
)


def test_m4_candidate_view_keeps_held_out_files_and_adds_only_m3_train_data(tmp_path: Path) -> None:
    repository = Path(__file__).parents[2]
    result = build_synthetic_visible_region_m4_view(
        repository,
        output_directory=tmp_path / "candidate-view",
    )

    root = result["root"]
    materialization = result["materialization"]
    assert materialization["campaign_id"] == "0068-m0-reviewed-rfdetr-local-visible-card-detector"
    assert materialization["counts"]["train_images"] == 545
    assert materialization["counts"]["train_annotations"] == 1546
    assert materialization["synthetic_training_view"]["merged_train_coco_sha256"]
    assert (root / "train").is_symlink()
    assert (root / "valid").is_symlink()
    assert (root / "sealed_test").is_symlink()
    loaded = _load_materialization_view(root)
    assert len(loaded["partitions"]["train"]) == 545

    merged = json.loads((root / "train" / "_annotations.coco.json").read_text())
    assert [image["dataset_origin"] for image in merged["images"][-8:]] == [
        "synthetic"
    ] * 8
    assert all(image.get("dataset_origin") != "synthetic" for image in merged["images"][:537])
    assert all(
        annotation.get("dataset_origin") != "synthetic"
        for annotation in merged["annotations"][:1535]
    )

    base = repository / ".runtime" / "rfdetr-segmentation-0068"
    assert (root / "valid" / "_annotations.coco.json").read_bytes() == (
        base / "valid" / "_annotations.coco.json"
    ).read_bytes()
    assert (root / "sealed_test" / "_annotations.coco.json").read_bytes() == (
        base / "sealed_test" / "_annotations.coco.json"
    ).read_bytes()
