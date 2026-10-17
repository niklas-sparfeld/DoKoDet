from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from doko_operations.card_plane_geometry import CardPlaneGeometryError, TablePlaneCalibration

FIXTURE = Path(__file__).parent / "fixtures/0099_img_0641_reciprocal_transform.json"


def test_img_0641_fit_loses_reciprocity_after_frozen_precision_rounding() -> None:
    fixture = json.loads(FIXTURE.read_text())
    image_to_table = np.asarray(fixture["image_to_table"], dtype=np.float64)
    table_to_image = np.asarray(fixture["table_to_image"], dtype=np.float64)
    assert np.allclose(image_to_table @ table_to_image, np.eye(3), atol=1e-12)

    decimals = fixture["rounding_decimals"]
    rounded_product = np.round(image_to_table, decimals) @ np.round(table_to_image, decimals)
    reciprocal_error = float(np.max(np.abs(rounded_product - np.eye(3))))
    assert reciprocal_error > fixture["reciprocal_check_atol"]

    with pytest.raises(CardPlaneGeometryError, match=fixture["observed_failure"]):
        TablePlaneCalibration.create(
            calibration_revision_id="fixture-img-0641",
            recording_id=fixture["source"]["recording_id"],
            source_revision=fixture["source"]["source_revision"],
            frame_width=fixture["frame_width"],
            frame_height=fixture["frame_height"],
            image_to_table=image_to_table,
            table_to_image=table_to_image,
            card_short_size=fixture["card_short_size"],
            card_long_size=fixture["card_long_size"],
            candidate_receipt_digests=[],
            diagnostics={},
        )
