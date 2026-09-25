from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from table_evidence_analyzer import visible_cards
from table_evidence_analyzer.visible_card_fine_prepass_provider import (
    FINE_PREPASS_PROVIDER_NAME,
    LocalVisibleCardFinePrepassProvider,
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
    checkpoint.write_bytes(b"fine-prepass-fixture-checkpoint")
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
        provider=FINE_PREPASS_PROVIDER_NAME,
        model=FINE_PREPASS_PROVIDER_NAME,
    )


class _Detector:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.calls = 0

    def predict(self, image: Image.Image, **_kwargs: object) -> object:
        self.calls += 1
        if self.mode == "failure" and self.calls == 2:
            raise RuntimeError("fixture crop failure")
        if self.calls == 1:
            boxes = [] if self.mode == "empty" else [[20, 20, 40, 40]]
        elif self.mode == "split":
            boxes = [[10, 10, 20, 30], [20, 10, 30, 30]]
        elif self.mode == "duplicates":
            boxes = [[10, 10, 30, 30], [10, 10, 30, 30]]
        else:
            boxes = [[10, 10, 30, 30]]
        return SimpleNamespace(
            xyxy=boxes,
            confidence=[0.9] * len(boxes),
            class_id=[0] * len(boxes),
        )


def _provider(tmp_path: Path, mode: str) -> tuple[LocalVisibleCardFinePrepassProvider, _Detector]:
    detector = _Detector(mode)
    return LocalVisibleCardFinePrepassProvider(
        _bundle(tmp_path), device="cpu", detector=detector
    ), detector


def test_empty_prepass_is_valid_negative_evidence_and_runs_no_crops(tmp_path: Path) -> None:
    provider, detector = _provider(tmp_path, "empty")

    result = provider.propose(_request())

    assert result.status == "ok"
    assert result.proposals == ()
    assert detector.calls == 1
    assert result.raw_response["prepass"]["status"] == "ok"
    assert result.raw_response["clusters"]["status"] == "empty"
    assert result.raw_response["refinement"]["status"] == "not_run"


def test_one_loaded_model_serves_prepass_and_crop(tmp_path: Path) -> None:
    detector = _Detector("single")
    loads: list[tuple[Path, str]] = []

    def load(bundle: object, device: str) -> _Detector:
        loads.append((bundle.checkpoint_path, device))
        return detector

    provider = LocalVisibleCardFinePrepassProvider(
        _bundle(tmp_path), device="cpu", model_loader=load
    )

    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(loads) == 1
    assert detector.calls == 2


def test_crop_split_supersedes_merged_prepass_with_source_mapped_cards(tmp_path: Path) -> None:
    provider, detector = _provider(tmp_path, "split")

    result = provider.propose(_request())

    assert result.status == "ok"
    assert detector.calls == 2
    assert len(result.proposals) == 2
    assert result.raw_response["arbitration"]["prepass_decisions"][0]["superseded"] is True
    assert result.raw_response["final_provenance"][0]["source"] == "crop"
    assert all(item["source_transform"] for item in result.raw_response["final_provenance"])
    assert "coarse" not in json.dumps(result.raw_response).lower()


def test_crop_failure_falls_back_to_full_frame_prepass(tmp_path: Path) -> None:
    provider, detector = _provider(tmp_path, "failure")

    result = provider.propose(_request())

    assert result.status == "ok"
    assert detector.calls == 2
    assert len(result.proposals) == 1
    assert result.raw_response["refinement"]["status"] == "partial"
    assert result.raw_response["refinement"]["clusters"][0]["status"] == "unavailable"
    assert result.raw_response["final_provenance"][0]["source"] == "prepass"


def test_duplicate_crop_outputs_reconcile_and_repeat_deterministically(tmp_path: Path) -> None:
    provider, _detector = _provider(tmp_path, "duplicates")

    first = provider.propose(_request())
    second = provider.propose(_request())

    assert first.status == second.status == "ok"
    assert len(first.proposals) == 1
    assert [item["prediction_id"] for item in first.raw_response["reconciliation"]["retained"]] == [
        item["prediction_id"] for item in second.raw_response["reconciliation"]["retained"]
    ]
    assert len(first.raw_response["reconciliation"]["discarded"]) == 1


def test_invalid_detection_does_not_drop_valid_threshold_boundary_card(tmp_path: Path) -> None:
    class BoundaryDetector:
        calls = 0

        def predict(self, image: Image.Image, **_kwargs: object) -> object:
            self.calls += 1
            if self.calls == 1:
                boxes = [[-1, 10, 10, 20], [0, 20, 20, 40]]
                scores = [0.9, 0.5]
            else:
                boxes = [[10, 10, 30, 30]]
                scores = [0.8]
            return SimpleNamespace(xyxy=boxes, confidence=scores, class_id=[0] * len(boxes))

    detector = BoundaryDetector()
    provider = LocalVisibleCardFinePrepassProvider(
        _bundle(tmp_path), device="cpu", detector=detector
    )

    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(result.proposals) == 1
    detections = result.raw_response["prepass"]["detections"]
    assert detections[0]["status"] == "rejected"
    assert detections[1]["status"] == "ok"
    assert result.raw_response["crop_routing_threshold"] == 0.5


def test_overlapping_crop_predictions_remain_separate_cards(tmp_path: Path) -> None:
    class OverlapDetector:
        calls = 0

        def predict(self, image: Image.Image, **_kwargs: object) -> object:
            self.calls += 1
            boxes = (
                [[20, 20, 40, 40], [30, 20, 50, 40]]
                if self.calls == 1
                else [[10, 15, 30, 35], [20, 15, 40, 35]]
            )
            return SimpleNamespace(xyxy=boxes, confidence=[0.9, 0.85], class_id=[0, 0])

    detector = OverlapDetector()
    provider = LocalVisibleCardFinePrepassProvider(
        _bundle(tmp_path), device="cpu", detector=detector
    )

    result = provider.propose(_request())

    assert result.status == "ok"
    assert result.raw_response["clusters"]["layout"]["clusters"]
    assert len(result.proposals) == 2
    assert result.raw_response["reconciliation"]["discarded"] == []


def test_exact_event_support_regions_survive_crop_arbitration(tmp_path: Path, monkeypatch) -> None:
    fixture_dir = Path(__file__).parent / "fixtures" / "visible_card_fine_prepass"
    manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))

    class FixtureDetector:
        def __init__(self, case: dict[str, object]) -> None:
            self.case = case
            self.calls = 0

        def predict(self, image: Image.Image, **_kwargs: object) -> object:
            self.calls += 1
            if self.calls > 1:
                return SimpleNamespace(xyxy=[], confidence=[], class_id=[], mask=[])
            regions = self.case["central_card_support_regions_normalized_1000"]
            boxes = [
                [
                    region["x_min"] * image.width / 1000,
                    region["y_min"] * image.height / 1000,
                    region["x_max"] * image.width / 1000,
                    region["y_max"] * image.height / 1000,
                ]
                for region in regions
            ]
            return SimpleNamespace(
                xyxy=boxes,
                confidence=[0.9] * len(boxes),
                class_id=[0] * len(boxes),
                mask=[[[index + 1]] for index in range(len(boxes))],
            )

    for case_index, case in enumerate(manifest["cases"]):
        regions = case["central_card_support_regions_normalized_1000"]
        polygons = []
        for region_index, region in enumerate(regions):
            x0 = region["x_min"] * case["width"] / 1000
            y0 = region["y_min"] * case["height"] / 1000
            x1 = region["x_max"] * case["width"] / 1000
            y1 = region["y_max"] * case["height"] / 1000
            if len(regions) == 1:
                polygons.append([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
            elif region_index == 0:
                polygons.append(
                    [[x0, y0], [x0 + (x1 - x0) * 0.58, y0], [x0 + (x1 - x0) * 0.58, y1], [x0, y1]]
                )
            else:
                polygons.append(
                    [[x0 + (x1 - x0) * 0.42, y0], [x1, y0], [x1, y1], [x0 + (x1 - x0) * 0.42, y1]]
                )

        monkeypatch.setattr(
            visible_cards,
            "_mask_to_polygons",
            lambda mask, values=polygons: [values[int(mask[0][0]) - 1]],
        )
        image_path = fixture_dir / case["image"]
        detector = FixtureDetector(case)
        provider = LocalVisibleCardFinePrepassProvider(
            _bundle(tmp_path / f"case-{case_index}"), device="cpu", detector=detector
        )
        with Image.open(image_path) as image:
            request = VisibleCardRequest(
                package_id=manifest["recording_id"],
                frame_part_name=case["event_id"],
                target_offset_ms=round(case["requested_time_us"] / 1000),
                image_bytes=image_path.read_bytes(),
                width=image.width,
                height=image.height,
                provider=FINE_PREPASS_PROVIDER_NAME,
                model=FINE_PREPASS_PROVIDER_NAME,
            )

        result = provider.propose(request)

        assert result.status == "ok"
        assert len(result.proposals) == len(regions)
        assert all(item["source"] == "prepass" for item in result.raw_response["final_provenance"])
        for proposal, region in zip(result.proposals, regions, strict=True):
            assert region["x_min"] <= proposal.box_2d.x_min
            assert proposal.box_2d.x_max <= region["x_max"]
            assert region["y_min"] <= proposal.box_2d.y_min
            assert proposal.box_2d.y_max <= region["y_max"]
