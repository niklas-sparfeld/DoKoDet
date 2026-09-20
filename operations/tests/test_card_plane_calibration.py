from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from doko_operations.card_plane_calibration import (
    CalibrationFailure,
    CalibrationRecipe,
    CalibrationRevisionStore,
    calibrate_recording,
)
from doko_operations.card_plane_geometry import project_fixed_card

TABLE_TO_IMAGE = np.asarray(
    [[120.0, 20.0, 420.0], [15.0, 100.0, 240.0], [0.0002, 0.0004, 1.0]],
    dtype=np.float64,
)


def _recording_result(
    *,
    positions: list[tuple[float, float]],
    recording_id: str = "recording-1",
    source_revision: str = "generated-1",
    transform: str = "camera-transform-1",
    duplicate: bool = False,
) -> dict[str, object]:
    frames = []
    for index, center in enumerate(positions):
        quad = project_fixed_card(TABLE_TO_IMAGE, center, (index % 3) * 8.0, 1.0, 1.5)
        frames.append(
            {
                "frame_id": f"frame-{index:03d}",
                "frame_index": index * 30,
                "timestamp_us": index * 1_000_000,
                "width": 1920,
                "height": 1080,
                "source_transform": transform,
                "predictions": [
                    {
                        "candidate_id": f"candidate-{index:03d}",
                        "confidence": 0.98,
                        "polygon": quad.tolist(),
                    }
                ],
            }
        )
    if duplicate:
        frames[0]["predictions"].append(
            {
                "candidate_id": "candidate-duplicate",
                "confidence": 0.97,
                "polygon": frames[0]["predictions"][0]["polygon"],
            }
        )
    return {
        "recording_id": recording_id,
        "source_revision": source_revision,
        "frames": frames,
    }


def test_calibration_is_repeatable_and_validates_held_out_candidates() -> None:
    result = _recording_result(
        positions=[
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
    )

    first = calibrate_recording(result)
    second = calibrate_recording(result)

    assert first.status == "published"
    assert first.calibration is not None
    assert first.to_mapping() == second.to_mapping()
    assert first.diagnostics["validation"]["held_out_count"] >= 2
    assert first.diagnostics["gates"]["held_out_alignment"] is True
    assert first.calibration.card_short_size == 1.0
    assert first.calibration.card_long_size == 1.5


def test_calibration_tolerates_one_held_out_crop_quality_region() -> None:
    result = _recording_result(
        positions=[
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
    )
    result["frames"][0]["predictions"][0]["polygon"] = [
        [100.0, 100.0],
        [210.0, 100.0],
        [245.0, 310.0],
        [100.0, 310.0],
    ]

    calibration = calibrate_recording(result)

    assert calibration.status == "published"
    validation = calibration.diagnostics["validation"]
    assert validation["held_out_aligned_count"] < validation["held_out_count"]
    assert validation["held_out_aligned_fraction"] >= 0.60


def test_calibration_rejects_a_globally_inconsistent_card_plane() -> None:
    result = _recording_result(
        positions=[
            (0.0, 0.0),
            (4.0, 0.0),
            (8.0, 0.0),
            (0.0, 3.0),
            (4.0, 3.0),
            (8.0, 3.0),
        ]
    )
    for index, frame in enumerate(result["frames"]):
        frame["predictions"][0]["polygon"] = project_fixed_card(
            TABLE_TO_IMAGE,
            ((index % 3) * 4.0, (index // 3) * 3.0),
            (index % 3) * 8.0,
            1.0,
            0.5 if index % 2 else 1.5,
        ).tolist()

    calibration = calibrate_recording(result)

    assert calibration.status == "failed"
    assert calibration.failure is not None
    assert calibration.failure.code == "inconsistent_card_geometry"


def test_candidate_mining_rejects_overlaps_and_deduplicates_bins() -> None:
    result = _recording_result(
        positions=[(0.0, 0.0), (4.0, 0.0), (8.0, 0.0), (0.0, 3.0), (4.0, 3.0), (8.0, 3.0)],
        duplicate=True,
    )

    calibration = calibrate_recording(
        result,
        recipe=CalibrationRecipe(minimum_candidates=5, minimum_temporal_bins=3),
    )

    receipts = {receipt.candidate_id: receipt for receipt in calibration.candidate_receipts}
    assert receipts["candidate-duplicate"].accepted is False
    assert receipts["candidate-duplicate"].rejection_reason == "overlaps_prediction"
    assert calibration.diagnostics["candidate_yield"]["deduplicated_count"] == 6


def test_one_long_lived_card_cannot_satisfy_diversity_gates() -> None:
    result = _recording_result(positions=[(4.0, 3.0)] * 12)

    calibration = calibrate_recording(result)

    assert calibration.status == "failed"
    assert calibration.failure is not None
    assert calibration.failure.code == "insufficient_diversity"
    assert "table position" in calibration.failure.message


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("width", 1280, "changed_frame_dimensions"),
        ("source_transform", "camera-transform-2", "changed_source_transform"),
    ],
)
def test_recording_inconsistency_is_an_actionable_failure(
    field: str, value: object, code: str
) -> None:
    result = _recording_result(
        positions=[(0.0, 0.0), (4.0, 0.0), (8.0, 0.0), (0.0, 3.0), (4.0, 3.0), (8.0, 3.0)]
    )
    result["frames"][3][field] = value

    calibration = calibrate_recording(result)

    assert calibration.status == "failed"
    assert calibration.failure is not None
    assert calibration.failure.code == code
    assert calibration.failure.action


def test_revision_store_does_not_overwrite_an_immutable_revision(tmp_path: Path) -> None:
    run = calibrate_recording(
        _recording_result(
            positions=[
                (0.0, 0.0),
                (4.0, 0.0),
                (8.0, 0.0),
                (0.0, 3.0),
                (4.0, 3.0),
                (8.0, 3.0),
                (0.0, 6.0),
                (4.0, 6.0),
                (8.0, 6.0),
            ]
        )
    )
    store = CalibrationRevisionStore(tmp_path)

    path = store.publish(run)
    assert path.is_file()
    assert (
        store.load("recording-1", run.calibration.calibration_revision_id).to_mapping()
        == run.to_mapping()
    )

    with pytest.raises(CalibrationFailure, match="immutable"):
        tampered = json.loads(path.read_text(encoding="utf-8"))
        tampered["diagnostics"]["candidate_yield"]["accepted_count"] = 999
        path.write_text(json.dumps(tampered), encoding="utf-8")
        store.publish(run)
