from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "visible_card_fine_prepass"


def test_fine_prepass_frames_are_source_linked_and_have_expected_central_regions() -> None:
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "visible-card-fine-prepass-regression-fixtures/v1"
    source = FIXTURE_ROOT / manifest["source_video"]["path"]
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert source_digest == manifest["source_video"]["sha256"]
    assert len(manifest["cases"]) == 2

    for case in manifest["cases"]:
        image_path = FIXTURE_ROOT / case["image"]
        image_bytes = image_path.read_bytes()
        assert hashlib.sha256(image_bytes).hexdigest() == case["image_sha256"]
        with Image.open(image_path) as image:
            assert image.size == (case["width"], case["height"])
            assert image.format == "JPEG"
        assert case["frame_identity"] == "exact-event/v1"
        assert case["expected_regions_are_reviewed_ground_truth"] is False
        assert case["central_card_support_regions_normalized_1000"]
        for region in case["central_card_support_regions_normalized_1000"]:
            assert 0 <= region["x_min"] < region["x_max"] <= 1000
            assert 0 <= region["y_min"] < region["y_max"] <= 1000
