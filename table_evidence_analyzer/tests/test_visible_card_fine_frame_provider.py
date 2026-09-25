from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from table_evidence_analyzer.visible_card_fine_frame_provider import (
    FINE_FRAME_PROVIDER_NAME,
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

    def predict(self, _image: Image.Image, **_kwargs: object) -> object:
        self.calls += 1
        boxes = [] if self.empty else [[20, 20, 40, 40]]
        return SimpleNamespace(xyxy=boxes, confidence=[0.9] * len(boxes), class_id=[0] * len(boxes))


def test_full_frame_provider_runs_one_inference_and_records_source_geometry(tmp_path: Path) -> None:
    detector = _Detector()
    provider = LocalVisibleCardFineFrameProvider(_bundle(tmp_path), device="cpu", detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(result.proposals) == 1
    assert detector.calls == 1
    assert result.raw_response["full_frame"]["status"] == "ok"
    assert result.raw_response["final_provenance"][0]["source"] == "full_frame"
    assert result.raw_response["timing"]["inference_latency_ms"] >= 0
    assert "clusters" not in result.raw_response
    assert "refinement" not in result.raw_response


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
            return SimpleNamespace(
                xyxy=[[-1, 10, 10, 20], [0, 20, 20, 40]],
                confidence=[0.9, 0.5],
                class_id=[0, 0],
            )

    detector = BoundaryDetector()
    provider = LocalVisibleCardFineFrameProvider(_bundle(tmp_path), device="cpu", detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(result.proposals) == 1
    detections = result.raw_response["full_frame"]["detections"]
    assert detections[0]["status"] == "rejected"
    assert detections[1]["status"] == "ok"
    assert result.raw_response["confidence_threshold"] == 0.5


def test_overlapping_full_frame_detections_remain_separate(tmp_path: Path) -> None:
    class OverlapDetector(_Detector):
        def predict(self, _image: Image.Image, **_kwargs: object) -> object:
            self.calls += 1
            return SimpleNamespace(
                xyxy=[[20, 20, 50, 50], [30, 20, 60, 50]],
                confidence=[0.9, 0.85],
                class_id=[0, 0],
            )

    detector = OverlapDetector()
    provider = LocalVisibleCardFineFrameProvider(_bundle(tmp_path), device="cpu", detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(result.proposals) == 2
    assert result.raw_response["reconciliation"]["discarded"] == []


def test_repeated_full_frame_output_is_deterministic(tmp_path: Path) -> None:
    detector = _Detector()
    provider = LocalVisibleCardFineFrameProvider(_bundle(tmp_path), device="cpu", detector=detector)

    first = provider.propose(_request())
    second = provider.propose(_request())

    assert first.status == second.status == "ok"
    assert [proposal.to_mapping() for proposal in first.proposals] == [
        proposal.to_mapping() for proposal in second.proposals
    ]
    assert detector.calls == 2
