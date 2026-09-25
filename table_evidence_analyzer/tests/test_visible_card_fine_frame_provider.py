from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from table_evidence_analyzer.visible_card_fine_frame_provider import (
    FINE_FRAME_PROVIDER_NAME,
    SMALL_CARD_CLUSTER_MAX_SIZE_FRACTION,
    LocalVisibleCardFineFrameProvider,
)
from table_evidence_analyzer.visible_cards import VisibleCardRequest


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _bundle(root: Path) -> Path:
    bundle = root / "bundle"
    bundle.mkdir(parents=True)
    checkpoint = bundle / "checkpoint_best_total.pth"
    checkpoint.write_bytes(b"fine-frame-fixture-checkpoint")
    checkpoint_digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    recipe = {"schema_version": "fixture-recipe/v1"}
    recipe["recipe_digest"] = _digest(recipe)
    manifest = {
        "schema_version": "rfdetr-segmentation-bundle/v1",
        "component": "visible-card-segmentation",
        "quality_state": "unreviewed",
        "model": {"class": "RFDETRSegMedium"},
        "model_variant": "rfdetr-seg-medium",
        "package": {"name": "rfdetr", "version": "1.9.4"},
        "class_map": {"1": "visible_card"},
        "input_size": [432, 432],
        "confidence_threshold": 0.5,
        "recipe": recipe,
        "checkpoint_file": checkpoint.name,
        "checkpoint_sha256": checkpoint_digest,
        "files": {checkpoint.name: checkpoint_digest},
    }
    manifest["bundle_digest"] = _digest(manifest)
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return bundle


def _request() -> VisibleCardRequest:
    output = BytesIO()
    Image.new("RGB", (100, 80), (30, 60, 90)).save(output, format="PNG")
    return VisibleCardRequest(
        package_id="recording-001",
        frame_part_name="event-001",
        target_offset_ms=125,
        image_bytes=output.getvalue(),
        width=100,
        height=80,
        provider=FINE_FRAME_PROVIDER_NAME,
        model=FINE_FRAME_PROVIDER_NAME,
    )


class _Detector:
    def __init__(self, *, empty: bool = False) -> None:
        self.empty = empty
        self.calls = 0

    def predict(self, image: Image.Image, **_kwargs: object) -> object:
        self.calls += 1
        if self.empty:
            boxes = []
        elif image.size == (100, 80):
            boxes = [[20, 20, 30, 30]]
        else:
            # The cluster crop starts at (15, 15), so this maps to the same
            # source-frame prediction as the prepass result.
            boxes = [[5, 5, 15, 15]]
        return SimpleNamespace(xyxy=boxes, confidence=[0.9] * len(boxes), class_id=[0] * len(boxes))


def test_provider_keeps_full_frame_when_matching_crop_has_no_score_gain(
    tmp_path: Path,
) -> None:
    detector = _Detector()
    provider = LocalVisibleCardFineFrameProvider(_bundle(tmp_path), device="cpu", detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(result.proposals) == 1
    assert detector.calls == 2
    assert result.raw_response["full_frame"]["status"] == "ok"
    assert result.raw_response["final_provenance"][0]["source"] == "full_frame"
    assert result.raw_response["timing"]["inference_latency_ms"] >= 0
    assert result.raw_response["clusters"]["status"] == "ok"
    assert result.raw_response["refinement"]["status"] == "ok"
    assert result.raw_response["arbitration"]["full_frame_candidates_removed"] == 0
    assert result.raw_response["arbitration"]["matched_pairs"][0]["decision"] == (
        "keep_full_frame_geometry"
    )


def test_empty_full_frame_result_is_valid_negative_evidence(tmp_path: Path) -> None:
    detector = _Detector(empty=True)
    provider = LocalVisibleCardFineFrameProvider(_bundle(tmp_path), device="cpu", detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    assert result.proposals == ()
    assert detector.calls == 1
    assert result.raw_response["full_frame"]["status"] == "ok"


def test_invalid_detection_does_not_drop_valid_threshold_boundary_card(tmp_path: Path) -> None:
    class BoundaryDetector(_Detector):
        def predict(self, _image: Image.Image, **_kwargs: object) -> object:
            self.calls += 1
            if self.calls > 1:
                return SimpleNamespace(xyxy=[], confidence=[], class_id=[])
            return SimpleNamespace(
                xyxy=[[-1, 10, 10, 20], [0, 20, 10, 30]],
                confidence=[0.9, 0.5],
                class_id=[0, 0],
            )

    detector = BoundaryDetector()
    provider = LocalVisibleCardFineFrameProvider(_bundle(tmp_path), device="cpu", detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(result.proposals) == 1
    assert detector.calls == 2
    detections = result.raw_response["full_frame"]["detections"]
    assert detections[0]["status"] == "rejected"
    assert detections[1]["status"] == "ok"
    assert result.raw_response["confidence_threshold"] == 0.5


def test_overlapping_full_frame_detections_remain_separate(tmp_path: Path) -> None:
    class OverlapDetector(_Detector):
        def predict(self, _image: Image.Image, **_kwargs: object) -> object:
            self.calls += 1
            if self.calls > 1:
                return SimpleNamespace(xyxy=[], confidence=[], class_id=[])
            return SimpleNamespace(
                xyxy=[[20, 20, 30, 30], [25, 20, 35, 30]],
                confidence=[0.9, 0.85],
                class_id=[0, 0],
            )

    detector = OverlapDetector()
    provider = LocalVisibleCardFineFrameProvider(_bundle(tmp_path), device="cpu", detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(result.proposals) == 2
    assert result.raw_response["reconciliation"]["discarded"] == []


def test_ambiguous_split_additions_preserve_the_full_frame_candidate(tmp_path: Path) -> None:
    class SplitDetector(_Detector):
        def predict(self, _image: Image.Image, **_kwargs: object) -> object:
            self.calls += 1
            boxes = [[20, 20, 30, 30]] if self.calls == 1 else [[5, 5, 10, 15], [10, 5, 15, 15]]
            return SimpleNamespace(
                xyxy=boxes,
                confidence=[0.9] * len(boxes) if self.calls == 1 else [0.98] * len(boxes),
                class_id=[0] * len(boxes),
            )

    detector = SplitDetector()
    provider = LocalVisibleCardFineFrameProvider(_bundle(tmp_path), device="cpu", detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(result.proposals) == 3
    assert [item["source"] for item in result.raw_response["final_provenance"]] == [
        "full_frame",
        "cluster_crop_addition",
        "cluster_crop_addition",
    ]
    assert result.raw_response["arbitration"]["full_frame_candidates_removed"] == 0
    assert result.raw_response["arbitration"]["full_frame_geometries_refined"] == 0


def test_unambiguous_higher_confidence_crop_refines_full_frame_geometry(tmp_path: Path) -> None:
    class Refiner:
        calls = 0

        def predict(self, image: Image.Image, **_kwargs: object) -> object:
            self.calls += 1
            is_full_frame = image.size == (100, 80)
            return SimpleNamespace(
                xyxy=[[20, 20, 30, 30]] if is_full_frame else [[5, 5, 14, 14]],
                confidence=[0.9] if is_full_frame else [0.98],
                class_id=[0],
            )

    detector = Refiner()
    provider = LocalVisibleCardFineFrameProvider(_bundle(tmp_path), device="cpu", detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(result.proposals) == 1
    assert result.proposals[0].box_2d.x_max == 290
    assert result.raw_response["final_provenance"][0]["source"] == "crop_refinement"
    assert result.raw_response["arbitration"]["full_frame_candidates_removed"] == 0
    assert result.raw_response["arbitration"]["full_frame_geometries_refined"] == 1


def test_small_score_gain_keeps_full_frame_geometry(tmp_path: Path) -> None:
    class Refiner:
        calls = 0

        def predict(self, image: Image.Image, **_kwargs: object) -> object:
            self.calls += 1
            is_full_frame = image.size == (100, 80)
            return SimpleNamespace(
                xyxy=[[20, 20, 30, 30]] if is_full_frame else [[5, 5, 14, 14]],
                confidence=[0.9] if is_full_frame else [0.94],
                class_id=[0],
            )

    detector = Refiner()
    provider = LocalVisibleCardFineFrameProvider(_bundle(tmp_path), device="cpu", detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(result.proposals) == 1
    assert result.proposals[0].box_2d.x_max == 300
    assert result.raw_response["final_provenance"][0]["source"] == "full_frame"
    assert result.raw_response["arbitration"]["matched_pairs"][0]["decision"] == (
        "keep_full_frame_geometry"
    )


def test_unmatched_crop_candidate_below_addition_threshold_is_discarded(tmp_path: Path) -> None:
    class LowConfidenceAddition(_Detector):
        def predict(self, image: Image.Image, **_kwargs: object) -> object:
            self.calls += 1
            if image.size == (100, 80):
                boxes, scores = [[20, 20, 30, 30]], [0.9]
            else:
                boxes, scores = [[10, 10, 15, 15]], [0.69]
            return SimpleNamespace(xyxy=boxes, confidence=scores, class_id=[0])

    detector = LowConfidenceAddition()
    provider = LocalVisibleCardFineFrameProvider(_bundle(tmp_path), device="cpu", detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(result.proposals) == 1
    assert result.raw_response["final_provenance"][0]["source"] == "full_frame"
    assert result.raw_response["reconciliation"]["discarded"][-1]["reason"] == (
        "below_crop_addition_threshold"
    )


def test_crop_failure_keeps_full_frame_predictions(tmp_path: Path) -> None:
    class FailureDetector(_Detector):
        def predict(self, _image: Image.Image, **_kwargs: object) -> object:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("fixture crop failure")
            return SimpleNamespace(xyxy=[[20, 20, 30, 30]], confidence=[0.9], class_id=[0])

    detector = FailureDetector()
    provider = LocalVisibleCardFineFrameProvider(_bundle(tmp_path), device="cpu", detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(result.proposals) == 1
    assert result.raw_response["refinement"]["status"] == "partial"
    assert result.raw_response["refinement"]["clusters"][0]["status"] == "unavailable"
    assert result.raw_response["final_provenance"][0]["source"] == "full_frame"


def test_provider_only_routes_small_clusters_that_gain_crop_resolution(tmp_path: Path) -> None:
    class DistanceDetector:
        calls = 0

        def predict(self, image: Image.Image, **_kwargs: object) -> object:
            self.calls += 1
            boxes = [[20, 20, 35, 35], [100, 50, 190, 130]] if image.size == (300, 200) else []
            return SimpleNamespace(
                xyxy=boxes,
                confidence=[0.9] * len(boxes),
                class_id=[0] * len(boxes),
            )

    output = BytesIO()
    Image.new("RGB", (300, 200), (30, 60, 90)).save(output, format="PNG")
    request = VisibleCardRequest(
        package_id="recording-far",
        frame_part_name="event-far",
        target_offset_ms=250,
        image_bytes=output.getvalue(),
        width=300,
        height=200,
        provider=FINE_FRAME_PROVIDER_NAME,
        model=FINE_FRAME_PROVIDER_NAME,
    )
    detector = DistanceDetector()
    provider = LocalVisibleCardFineFrameProvider(_bundle(tmp_path), device="cpu", detector=detector)

    result = provider.propose(request)

    assert result.status == "ok"
    assert detector.calls == 2
    assert result.raw_response["clusters"]["routed_cluster_ids"] == ["cluster-0001"]
    routing = result.raw_response["clusters"]["routing"]
    assert routing[0]["card_size_metric"] == "longer_visible_box_side"
    assert routing[0]["minimum_card_size_model_px"] < 432 * SMALL_CARD_CLUSTER_MAX_SIZE_FRACTION
    assert routing[0]["route"] is True
    assert routing[1]["minimum_card_size_model_px"] > 432 * SMALL_CARD_CLUSTER_MAX_SIZE_FRACTION
    assert routing[1]["route"] is False
    assert [item["status"] for item in result.raw_response["refinement"]["clusters"]] == [
        "ok",
        "skipped",
    ]
    assert len(result.proposals) == 2


def test_repeated_full_frame_output_is_deterministic(tmp_path: Path) -> None:
    detector = _Detector()
    provider = LocalVisibleCardFineFrameProvider(_bundle(tmp_path), device="cpu", detector=detector)

    first = provider.propose(_request())
    second = provider.propose(_request())

    assert first.status == second.status == "ok"
    assert [proposal.to_mapping() for proposal in first.proposals] == [
        proposal.to_mapping() for proposal in second.proposals
    ]
    assert detector.calls == 4
