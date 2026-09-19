from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from doko_operations.synthetic_visible_region_materialization import (
    build_synthetic_visible_region_inputs,
    validate_synthetic_visible_region_inputs,
)


def _card_source(root: Path) -> None:
    image = np.full((800, 600, 3), 20, dtype=np.uint8)
    quad = np.array([[150, 90], [450, 80], [470, 710], [130, 720]], dtype=np.int32)
    cv2.fillConvexPoly(image, quad, (238, 238, 238))
    cv2.polylines(image, [quad], True, (80, 80, 80), 4)
    cv2.circle(image, (300, 400), 45, (30, 30, 30), -1)
    root.mkdir(parents=True)
    assert cv2.imwrite(str(root / "card.png"), image)


def test_m1_materialization_is_reproducible_and_writes_an_alpha_cutout(tmp_path: Path) -> None:
    source_root = tmp_path / "cards"
    _card_source(source_root)

    first = build_synthetic_visible_region_inputs(
        tmp_path,
        source_directory=source_root,
        output_directory=tmp_path / ".runtime" / "m1",
        m0_manifest_path=tmp_path / "missing-m0.json",
        table_input_spec=None,
    )
    second = build_synthetic_visible_region_inputs(
        tmp_path,
        source_directory=source_root,
        output_directory=tmp_path / ".runtime" / "m1",
        m0_manifest_path=tmp_path / "missing-m0.json",
        table_input_spec=None,
    )

    assert first == second
    assert first["inventory"]["cutout_count"] == 1
    assert first["inventory"]["side_counts"] == {"face_down": 0, "face_up": 1, "unknown": 0}
    assert first["inventory"]["background_count"] == 0
    assert first["freeze_state"] == "blocked"
    cutout = first["cutouts"][0]
    assert cutout["roundtrip_max_pixel_error"] <= 0.01
    assert cutout["alpha_fraction"] > 0.7
    assert (tmp_path / cutout["files"]["rgba"]["path"]).is_file()
    validate_synthetic_visible_region_inputs(first)


def test_m1_excludes_a_sealed_test_table_link_without_decoding_it(tmp_path: Path) -> None:
    source_root = tmp_path / "cards"
    _card_source(source_root)
    manifest_path = tmp_path / "data" / "operations" / (
        "rfdetr-visible-card-detector-0068-m0-manifest.json"
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "recordings": [
                    {
                        "recording_id": "sealed-recording",
                        "split": "sealed_test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    spec_path = tmp_path / "table-inputs.json"
    spec_path.write_text(
        json.dumps(
            {
                "schema_version": "synthetic-visible-region-table-inputs/v1",
                "inputs": [
                    {
                        "input_id": "sealed-card",
                        "url": "http://localhost/sealed",
                        "role": "card",
                        "recording_id": "sealed-recording",
                        "event_id": "sealed-event",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = build_synthetic_visible_region_inputs(
        tmp_path,
        source_directory=source_root,
        output_directory=tmp_path / ".runtime" / "m1",
        m0_manifest_path=tmp_path / "missing-m0.json",
        table_input_spec=spec_path,
    )

    assert manifest["operator_review_links"] == []
    assert manifest["excluded_review_inputs"][0]["source_split"] == "sealed_test"
    assert (
        manifest["excluded_review_inputs"][0]["excluded_reason"]
        == "validation_or_sealed_test_source_group_not_allowed"
    )
    validate_synthetic_visible_region_inputs(manifest)
