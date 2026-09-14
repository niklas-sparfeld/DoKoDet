from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import table_evidence_analyzer.visible_cards as visible_cards
from table_evidence_analyzer.visible_card_training import VISIBLE_CARD_BUNDLE_SCHEMA
from table_evidence_analyzer.visible_cards import (
    LOCAL_PROVIDER_NAME,
    LocalVisibleCardProvider,
    VisibleCardError,
    VisibleCardRequest,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _bundle(root: Path) -> Path:
    bundle = root / "bundle"
    bundle.mkdir()
    checkpoint = bundle / "checkpoint_best_total.pth"
    checkpoint.write_bytes(b"fixture-native-checkpoint")
    checkpoint_digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    recipe = {"recipe_digest": "placeholder"}
    recipe["recipe_digest"] = _digest(
        {key: value for key, value in recipe.items() if key != "recipe_digest"}
    )
    manifest = {
        "schema_version": VISIBLE_CARD_BUNDLE_SCHEMA,
        "component": "visible-card-detector",
        "quality_state": "unreviewed",
        "model_variant": "RFDETRLarge",
        "package": {"name": "rfdetr", "version": "1.9.4"},
        "class_map": {"1": "visible_card"},
        "input_size": [704, 704],
        "confidence_threshold": 0.5,
        "non_maximum_suppression": False,
        "recipe_digest": recipe["recipe_digest"],
        "recipe": recipe,
        "run_id": "visible-card-m1-fixture",
        "checkpoint_file": checkpoint.name,
        "checkpoint_sha256": checkpoint_digest,
        "files": {checkpoint.name: checkpoint_digest},
    }
    manifest["bundle_digest"] = _digest(manifest)
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return bundle


def _image() -> bytes:
    output = BytesIO()
    Image.new("RGB", (20, 20), (120, 80, 40)).save(output, format="JPEG")
    return output.getvalue()


def _request(image: bytes | None = None) -> VisibleCardRequest:
    return VisibleCardRequest(
        package_id="package-001",
        frame_part_name="frame_00",
        target_offset_ms=0,
        image_bytes=image or _image(),
        width=20,
        height=20,
        provider=LOCAL_PROVIDER_NAME,
        model="local-rfdetr",
    )


class _Detector:
    def __init__(self, detections: object = None, error: Exception | None = None) -> None:
        self.detections = detections
        self.error = error
        self.calls: list[dict[str, object]] = []

    def predict(self, image: object, **kwargs: object) -> object:
        self.calls.append({"image": image, **kwargs})
        if self.error:
            raise self.error
        return self.detections


def _detections(
    boxes: list[list[float]],
    scores: list[float],
    class_ids: list[int],
    masks: object | None = None,
) -> object:
    return SimpleNamespace(
        xyxy=boxes,
        confidence=scores,
        class_id=class_ids,
        mask=masks,
    )


@pytest.mark.parametrize(
    ("boxes", "scores", "class_ids", "expected_count"),
    [
        ([], [], [], 0),
        ([[2.0, 4.0, 12.0, 16.0]], [0.75], [0], 1),
        (
            [
                [1.0, 2.0, 5.0, 8.0],
                [10.0, 5.0, 19.0, 19.0],
            ],
            [0.8, 0.9],
            [0, 0],
            2,
        ),
    ],
)
def test_local_provider_converts_rfdetr_detections_and_records_provenance(
    tmp_path: Path,
    boxes: list[list[float]],
    scores: list[float],
    class_ids: list[int],
    expected_count: int,
) -> None:
    detector = _Detector(_detections(boxes, scores, class_ids))
    provider = LocalVisibleCardProvider(_bundle(tmp_path), device="cpu", detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(result.proposals) == expected_count
    assert result.latency_ms >= 0
    assert result.raw_response["provider"] == LOCAL_PROVIDER_NAME
    assert result.raw_response["device"] == "cpu"
    assert (
        result.raw_response["bundle_identity"]["bundle_digest"]
        == provider.bundle_identity["bundle_digest"]
    )
    assert result.raw_response["detector_scores"] == scores
    assert detector.calls[0]["threshold"] == 0.5
    assert detector.calls[0]["shape"] == (704, 704)
    assert detector.calls[0]["include_source_image"] is False
    if expected_count == 1:
        proposal = result.proposals[0]
        assert proposal.box_2d.to_mapping() == {
            "x_min": 100,
            "y_min": 200,
            "x_max": 600,
            "y_max": 800,
        }
        assert proposal.side == "unknown"
        assert proposal.label == "visible_card"
        assert proposal.polygon[2].to_mapping() == {"x": 600, "y": 800}
        assert result.raw_response["detections"][0]["geometry_source"] == "detector_box"


def test_local_provider_uses_segmentation_polygon_and_derives_its_tight_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        visible_cards,
        "_mask_to_polygons",
        lambda _mask: [[[2, 4], [12, 4], [10, 16], [2, 16]]],
    )
    detector = _Detector(
        _detections(
            [[1.0, 1.0, 19.0, 19.0]],
            [0.75],
            [0],
            masks=[[[False, True]]],
        )
    )
    provider = LocalVisibleCardProvider(_bundle(tmp_path), detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    proposal = result.proposals[0]
    assert proposal.polygon == (
        visible_cards.NormalizedPoint(x=100, y=200),
        visible_cards.NormalizedPoint(x=600, y=200),
        visible_cards.NormalizedPoint(x=500, y=800),
        visible_cards.NormalizedPoint(x=100, y=800),
    )
    assert proposal.box_2d.to_mapping() == {
        "x_min": 100,
        "y_min": 200,
        "x_max": 600,
        "y_max": 800,
    }
    assert result.raw_response["detections"][0]["geometry_source"] == "segmentation_mask"
    assert result.raw_response["detections"][0]["visible_polygon"] == [
        {"x": 100, "y": 200},
        {"x": 600, "y": 200},
        {"x": 500, "y": 800},
        {"x": 100, "y": 800},
    ]


def test_local_provider_keeps_largest_component_of_disconnected_mask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        visible_cards,
        "_mask_to_polygons",
        lambda _mask: [
            [[2, 2], [18, 2], [18, 18], [2, 18]],
            [[0, 0], [1, 0], [1, 1]],
        ],
    )
    detector = _Detector(
        _detections(
            [[1.0, 1.0, 19.0, 19.0]],
            [0.75],
            [0],
            masks=[[[False, True]]],
        )
    )
    provider = LocalVisibleCardProvider(_bundle(tmp_path), detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(result.proposals) == 1
    assert result.proposals[0].box_2d.to_mapping() == {
        "x_min": 100,
        "y_min": 100,
        "x_max": 900,
        "y_max": 900,
    }
    detection = result.raw_response["detections"][0]
    assert detection["mask_component_count"] == 2
    assert detection["mask_repaired"] is True
    assert detection["selected_component_area_px"] == 256.0
    assert detection["discarded_component_area_px"] == 0.5
    assert result.raw_response["skipped_detections"] == []


def test_local_provider_returns_ok_empty_prediction_for_empty_mask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(visible_cards, "_mask_to_polygons", lambda _mask: [])
    detector = _Detector(
        _detections(
            [[1.0, 1.0, 19.0, 19.0]],
            [0.75],
            [0],
            masks=[[[False, False]]],
        )
    )
    provider = LocalVisibleCardProvider(_bundle(tmp_path), detector=detector)

    result = provider.propose(_request())

    assert result.status == "ok"
    assert result.proposals == ()
    assert result.raw_response["detections"] == []
    assert result.raw_response["detector_scores"] == []
    assert result.raw_response["skipped_detections"][0]["geometry_source"] == (
        "segmentation_mask_empty"
    )
    assert result.raw_response["skipped_detections"][0]["mask_component_count"] == 0


def test_local_provider_returns_unavailable_for_invalid_input_and_inference_failure(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    invalid = LocalVisibleCardProvider(bundle, detector=_Detector()).propose(
        _request(b"not-an-image")
    )
    assert invalid.status == "unavailable"
    assert "could not be decoded" in invalid.error

    failed = LocalVisibleCardProvider(
        bundle,
        detector=_Detector(error=RuntimeError("operator test failure")),
    ).propose(_request())
    assert failed.status == "unavailable"
    assert "operator test failure" in failed.error
    assert failed.proposals == ()


def test_local_provider_rejects_a_tampered_bundle_before_inference(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    (bundle / "checkpoint_best_total.pth").write_bytes(b"tampered")

    with pytest.raises(VisibleCardError, match="could not validate"):
        LocalVisibleCardProvider(bundle, detector=_Detector())


def test_local_provider_does_not_fallback_when_mps_is_unavailable(tmp_path: Path) -> None:
    torch_module = SimpleNamespace(
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False))
    )

    with pytest.raises(VisibleCardError, match="device is unavailable: mps"):
        LocalVisibleCardProvider(
            _bundle(tmp_path),
            device="mps",
            detector=_Detector(),
            torch_module=torch_module,
        )
