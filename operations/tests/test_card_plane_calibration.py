from __future__ import annotations

import json
import sys
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from card_plane_calibration_baseline import _synthetic_result  # noqa: E402

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


def test_calibration_accepts_generated_revision_identifiers() -> None:
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
        ],
        source_revision="visible-cards-visible_cards-run-5bd52a7b-3ba-attempt-1",
    )

    run = calibrate_recording(result)

    assert run.status == "published"


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


def test_candidate_selection_rejects_nonstandard_apparent_card_scale() -> None:
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
    assert calibration.failure.code == "insufficient_candidates"
    evidence = {
        item["candidate_id"]: item for item in calibration.diagnostics["candidate_evidence"]
    }
    assert (
        sum(
            item["rejection_reason"] == "inconsistent_apparent_card_scale"
            for item in evidence.values()
        )
        >= 2
    )


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


def test_candidate_evidence_carries_uniform_boundaries_and_quality() -> None:
    result, _references, _metadata = _synthetic_result("clean-isolated")

    run = calibrate_recording(result)

    assert run.status == "published"
    assert len(run.candidate_receipts) == 12
    for receipt in run.candidate_receipts:
        assert len(receipt.boundary_samples) == 64
        assert dict(receipt.quality_metrics)["mask_quad_iou"] > 0.9
        assert dict(receipt.quality_metrics)["boundary_straightness"] > 0.9
        assert receipt.source_revision == result["source_revision"]
        assert receipt.source_frame_id.startswith("frame-")


@pytest.mark.parametrize(
    ("case_id", "candidate_ids", "reason"),
    [
        ("overlapping-pile", ["pile-card-04b"], "overlaps_prediction"),
        ("partial-card", ["card-04"], "inconsistent_apparent_card_scale"),
        ("weak-mask", ["card-05"], "confidence_below_threshold"),
        (
            "outlier",
            ["outlier-card-04", "outlier-card-09"],
            "inconsistent_apparent_card_scale",
        ),
        ("clipped-card", ["card-00"], "frame_boundary"),
    ],
)
def test_candidate_selection_rejects_frozen_m0_evidence_cases(
    case_id: str, candidate_ids: list[str], reason: str
) -> None:
    result, _references, _metadata = _synthetic_result(case_id)

    run = calibrate_recording(result)
    evidence = {item["candidate_id"]: item for item in run.diagnostics["candidate_evidence"]}

    for candidate_id in candidate_ids:
        assert evidence[candidate_id]["accepted"] is False
        assert evidence[candidate_id]["rejection_reason"] == reason
        assert evidence[candidate_id]["source_revision"] == result["source_revision"]
        assert evidence[candidate_id]["source_frame_id"]


def test_candidate_selection_keeps_full_edge_and_uniformly_shrunken_cards() -> None:
    edge_result, _references, _metadata = _synthetic_result("edge-of-view")
    shrink_result, _references, _metadata = _synthetic_result("shrink-10-percent")

    edge_run = calibrate_recording(edge_result)
    shrink_run = calibrate_recording(shrink_result)

    edge_evidence = {
        item["candidate_id"]: item for item in edge_run.diagnostics["candidate_evidence"]
    }
    shrink_evidence = {
        item["candidate_id"]: item for item in shrink_run.diagnostics["candidate_evidence"]
    }
    assert edge_evidence["card-00"]["accepted"] is True
    assert all(item["accepted"] for item in shrink_evidence.values())


def test_candidate_selection_uses_common_local_geometry_and_rejects_fragments() -> None:
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
        ]
    )
    for frame in result["frames"]:
        prediction = frame["predictions"][0]
        polygon = prediction.pop("polygon")
        prediction["geometry"] = {"visible_region": {"polygons": [polygon]}}
        prediction["score"] = prediction.pop("confidence")
    fragmented = result["frames"][-1]["predictions"][0]
    fragmented["candidate_id"] = "fragmented-card"
    fragmented["geometry"]["visible_region"]["polygons"].append(
        [[1500.0, 800.0], [1540.0, 800.0], [1540.0, 850.0], [1500.0, 850.0]]
    )

    run = calibrate_recording(result)

    evidence = {item["candidate_id"]: item for item in run.diagnostics["candidate_evidence"]}
    assert evidence["fragmented-card"]["accepted"] is False
    assert evidence["fragmented-card"]["rejection_reason"] == "disconnected_components"
    assert all(
        len(receipt.boundary_samples) == 64
        for receipt in run.candidate_receipts
        if receipt.accepted
    )


@pytest.mark.parametrize("confidence", [None, float("nan"), 1.2])
def test_candidate_selection_records_invalid_confidence(confidence: float | None) -> None:
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
        ]
    )
    result["frames"][0]["predictions"][0]["confidence"] = confidence

    run = calibrate_recording(result)
    evidence = {item["candidate_id"]: item for item in run.diagnostics["candidate_evidence"]}

    assert evidence["candidate-000"]["accepted"] is False
    assert evidence["candidate-000"]["rejection_reason"] == "invalid_confidence"
    assert evidence["candidate-000"]["confidence"] is None


def test_candidate_selection_caps_frame_and_temporal_influence() -> None:
    positions = [
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
    frame_result = _recording_result(positions=positions)
    first_frame = frame_result["frames"][0]
    for index, frame in enumerate(frame_result["frames"][1:], start=1):
        prediction = dict(frame["predictions"][0])
        prediction["candidate_id"] = f"same-frame-{index:02d}"
        first_frame["predictions"].append(prediction)

    frame_run = calibrate_recording(frame_result)
    accepted_from_first = [
        receipt
        for receipt in frame_run.candidate_receipts
        if receipt.accepted and receipt.source_frame_id == "frame-000"
    ]
    assert len(accepted_from_first) <= 4
    assert any(
        item["rejection_reason"] == "frame_observation_cap"
        for item in frame_run.diagnostics["candidate_evidence"]
    )

    temporal_result = _recording_result(positions=positions)
    for frame in temporal_result["frames"]:
        frame["timestamp_us"] = 0
    temporal_run = calibrate_recording(temporal_result)
    accepted_in_interval = [
        receipt
        for receipt in temporal_run.candidate_receipts
        if receipt.accepted and receipt.temporal_bin == "t-0"
    ]
    assert len(accepted_in_interval) <= 8
    assert any(
        item["rejection_reason"] == "temporal_bin_observation_cap"
        for item in temporal_run.diagnostics["candidate_evidence"]
    )


def test_one_long_lived_card_cannot_satisfy_diversity_gates() -> None:
    result = _recording_result(positions=[(4.0, 3.0)] * 12)

    calibration = calibrate_recording(result)

    assert calibration.status == "failed"
    assert calibration.failure is not None
    assert calibration.failure.code == "insufficient_diversity"
    assert "table position" in calibration.failure.message
    accepted = [item for item in calibration.candidate_receipts if item.accepted]
    assert len(accepted) <= 8
    assert any(
        item.rejection_reason == "position_bin_observation_cap"
        for item in calibration.candidate_receipts
    )


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
