from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import table_evidence_analyzer.visible_card_cascade_provider as cascade_provider
from table_evidence_analyzer.visible_card_cascade_provider import (
    CASCADE_PROVIDER_NAME,
    LocalVisibleCardCascadeProvider,
)
from table_evidence_analyzer.visible_cards import VisibleCardError, VisibleCardRequest


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _bundle(root: Path) -> Path:
    bundle = root / "bundle"
    bundle.mkdir(parents=True)
    checkpoint = bundle / "checkpoint_best_total.pth"
    checkpoint.write_bytes(b"fixture-0068-checkpoint")
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


def _image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (100, 80), (40, 80, 120)).save(output, format="PNG")
    return output.getvalue()


def _request(image_bytes: bytes | None = None) -> VisibleCardRequest:
    return VisibleCardRequest(
        package_id="recording-001",
        frame_part_name="event-001",
        target_offset_ms=125,
        image_bytes=image_bytes or _image_bytes(),
        width=100,
        height=80,
        provider=CASCADE_PROVIDER_NAME,
        model="local-rfdetr-cascade",
    )


class _Detector:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.calls: list[tuple[int, int]] = []
        self.fail_on_call = fail_on_call

    def predict(self, image: Image.Image, **_kwargs: object) -> object:
        self.calls.append(image.size)
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("fixture detector failure")
        if image.size == (100, 80):
            return SimpleNamespace(
                xyxy=[[10, 20, 30, 40], [70, 20, 90, 40]],
                confidence=[0.9, 0.8],
                class_id=[0, 0],
                mask=[[[True]], [[True]]],
            )
        return SimpleNamespace(
            xyxy=[[5, 5, 35, 35]],
            confidence=[0.95],
            class_id=[0],
            mask=[[[True]]],
        )


def test_cascade_reuses_one_model_maps_source_candidates_and_retains_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cascade_provider.visible_cards,
        "_mask_to_polygons",
        lambda _mask: [
            [[5, 5], [25, 5], [25, 25], [5, 25]],
            [[27, 27], [35, 27], [35, 35], [27, 35]],
        ],
    )
    detector = _Detector()
    loader_calls: list[tuple[Path, str]] = []

    def load(bundle: object, device: str) -> _Detector:
        loader_calls.append((bundle.checkpoint_path, device))
        return detector

    provider = LocalVisibleCardCascadeProvider(
        _bundle(tmp_path), device="cpu", model_loader=load
    )
    result = provider.propose(_request())

    assert result.status == "ok"
    assert len(loader_calls) == 1
    assert detector.calls == [(100, 80), (40, 40), (40, 40)]
    assert len(result.proposals) == 2
    assert all(len(proposal.polygons or ()) == 2 for proposal in result.proposals)
    assert all(
        proposal.box_2d == cascade_provider.visible_cards._tight_box_for_polygon(
            [point for component in proposal.polygons or () for point in component]
        )
        for proposal in result.proposals
    )
    assert result.raw_response["source_frame"]["frame_part_name"] == "event-001"
    assert result.raw_response["coarse"]["layout"]["clusters"]
    assert all(
        detection["mask_ignored_for_clustering"]
        for detection in result.raw_response["coarse"]["detections"]
    )
    assert len(result.raw_response["fine"]["clusters"]) == 2
    assert result.raw_response["fine"]["clusters"][0]["crop_image_sha256"]
    assert all(
        len(prediction["polygons"]) == 2
        for prediction in result.raw_response["mapping"]["predictions"]
    )
    assert result.raw_response["timing"]["fine_latency_ms"] >= 0


def test_cascade_keeps_coarse_failure_and_partial_fine_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cascade_provider.visible_cards,
        "_mask_to_polygons",
        lambda _mask: [[[5, 5], [35, 5], [35, 35], [5, 35]]],
    )
    coarse_failure = LocalVisibleCardCascadeProvider(
        _bundle(tmp_path / "coarse"),
        device="cpu",
        detector=_Detector(fail_on_call=1),
    ).propose(_request())
    assert coarse_failure.status == "unavailable"
    assert coarse_failure.proposals == ()
    assert coarse_failure.raw_response["coarse"]["status"] == "unavailable"
    assert coarse_failure.raw_response["source_frame"]["image_sha256"]

    partial_detector = _Detector(fail_on_call=3)
    partial = LocalVisibleCardCascadeProvider(
        _bundle(tmp_path / "partial"),
        device="cpu",
        detector=partial_detector,
    ).propose(_request())
    assert partial.status == "unavailable"
    assert partial.proposals == ()
    assert partial.raw_response["fine"]["status"] == "unavailable"
    assert len(partial.raw_response["fine"]["clusters"]) == 2
    assert partial.raw_response["fine"]["clusters"][0]["status"] == "ok"
    assert partial.raw_response["fine"]["clusters"][1]["status"] == "unavailable"


def test_cascade_rejects_requests_for_another_provider(tmp_path: Path) -> None:
    provider = LocalVisibleCardCascadeProvider(
        _bundle(tmp_path), device="cpu", detector=_Detector()
    )
    request = _request()
    request = replace(request, provider="local-rfdetr-segmentation")
    with pytest.raises(VisibleCardError, match="does not match"):
        provider.propose(request)


def test_cascade_serializes_shared_model_inference_across_requests(tmp_path: Path) -> None:
    class ConcurrentDetector(_Detector):
        def __init__(self) -> None:
            super().__init__()
            self.active = 0
            self.max_active = 0
            self._lock = threading.Lock()

        def predict(self, image: Image.Image, **kwargs: object) -> object:
            with self._lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                time.sleep(0.01)
                return super().predict(image, **kwargs)
            finally:
                with self._lock:
                    self.active -= 1

    detector = ConcurrentDetector()
    provider = LocalVisibleCardCascadeProvider(
        _bundle(tmp_path), device="cpu", detector=detector
    )
    first = threading.Thread(target=provider.propose, args=(_request(),))
    second = threading.Thread(target=provider.propose, args=(_request(),))

    first.start()
    second.start()
    first.join()
    second.join()

    assert detector.max_active == 1


@pytest.mark.parametrize(
    ("device", "expected_dtype"),
    [("cpu", "float32"), ("mps", "float16"), ("cuda", "float16")],
)
def test_local_rfdetr_loader_optimizes_models_for_inference(
    device: str, expected_dtype: str
) -> None:
    calls: list[dict[str, object]] = []

    class Model:
        def inference(self, **kwargs: object) -> None:
            calls.append(kwargs)

    model = Model()

    assert cascade_provider.visible_cards._optimize_local_rfdetr_for_inference(
        model, device=device
    ) is model
    assert calls == [
        {"compile": False, "dtype": expected_dtype, "inplace": True}
    ]
