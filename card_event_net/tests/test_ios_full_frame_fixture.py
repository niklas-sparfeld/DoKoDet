from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from cardevent.cache import _full_frame_letterbox


def test_ios_full_frame_fixture_matches_python_reference() -> None:
    fixture_path = (
        Path(__file__).parents[2]
        / "ios"
        / "CardEventProbeTests"
        / "Fixtures"
        / "full_frame_letterbox_v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    pixels = np.asarray(fixture["pixels_bgra"], dtype=np.uint8).reshape(
        fixture["source_height"], fixture["source_width"], 4
    )

    letterboxed_bgr = _full_frame_letterbox(
        pixels[:, :, :3],
        size=fixture["target_size"],
        cv2=cv2,
    )
    rgb = letterboxed_bgr[:, :, ::-1].astype(np.float32) / np.float32(255.0)
    mean = np.asarray((0.485, 0.456, 0.406), dtype=np.float32)
    standard_deviation = np.asarray((0.229, 0.224, 0.225), dtype=np.float32)
    frame = ((rgb - mean) / standard_deviation).transpose(2, 0, 1)
    tensor = np.repeat(frame[None, None, :, :, :], fixture["frame_count"], axis=1)

    digest = hashlib.sha256(np.asarray(tensor, dtype="<f4").tobytes(order="C")).hexdigest()
    assert digest == fixture["python_reference"]["sha256"]
