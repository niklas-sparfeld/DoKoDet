from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import table_evidence_analyzer.visible_card_cascade_provider as cascade_provider
from table_evidence_analyzer.rfdetr_cascade import (
    RFDETR_CASCADE_BUNDLE_SCHEMA,
    RfdetrCascadeBundleError,
    assemble_rfdetr_cascade_bundle,
    load_rfdetr_cascade_bundle,
)
from table_evidence_analyzer.rfdetr_cascade_evaluation import (
    RfdetrCascadeValidationCase,
    run_rfdetr_cascade_validation,
)
from table_evidence_analyzer.visible_card_cascade import PixelBox
from table_evidence_analyzer.visible_card_cascade_provider import (
    LocalVisibleCardCascadeProvider,
)
from table_evidence_analyzer.visible_cards import VisibleCardRequest


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _child_bundles(root: Path) -> tuple[Path, Path]:
    coarse = root / "coarse"
    coarse.mkdir(parents=True)
    coarse_checkpoint = coarse / "checkpoint_best_total.pth"
    coarse_checkpoint.write_bytes(b"m3-coarse-checkpoint")
    coarse_report = {"report_digest": "a" * 64}
    _write_json(coarse / "validation-report.json", coarse_report)
    coarse_recipe = {"schema_version": "m3-fixture-recipe/v1"}
    coarse_manifest = {
        "schema_version": "rfdetr-card-cluster-bundle/v1",
        "component": "card-cluster-detection",
        "quality_state": "unreviewed",
        "model": {"class": "RFDETRSmall"},
        "model_variant": "rfdetr-small",
        "package": {"name": "rfdetr", "version": "1.9.4"},
        "class_map": {"1": "card_cluster"},
        "input_size": [512, 512],
        "confidence_threshold": 0.6,
        "recipe": {**coarse_recipe, "recipe_digest": _digest(coarse_recipe)},
        "validation_report": {
            "file": coarse_report and "validation-report.json",
            "report_digest": coarse_report["report_digest"],
        },
        "validation": {"selected_threshold": 0.6},
        "checkpoint_file": coarse_checkpoint.name,
        "checkpoint_sha256": hashlib.sha256(coarse_checkpoint.read_bytes()).hexdigest(),
        "pretrained_checkpoint": {"sha256": "b" * 64},
        "files": {
            coarse_checkpoint.name: hashlib.sha256(coarse_checkpoint.read_bytes()).hexdigest(),
            "validation-report.json": hashlib.sha256(
                (coarse / "validation-report.json").read_bytes()
            ).hexdigest(),
        },
    }
    coarse_manifest["bundle_digest"] = _digest(
        {key: value for key, value in coarse_manifest.items() if key != "bundle_digest"}
    )
    _write_json(coarse / "manifest.json", coarse_manifest)

    fine = root / "fine"
    fine.mkdir(parents=True)
    fine_checkpoint = fine / "checkpoint_best_total.pth"
    fine_checkpoint.write_bytes(b"m5-fine-checkpoint")
    fine_recipe = {"schema_version": "m5-fixture-recipe/v1"}
    fine_manifest = {
        "schema_version": "rfdetr-segmentation-bundle/v1",
        "component": "visible-card-segmentation",
        "quality_state": "unreviewed",
        "model": {"class": "RFDETRSegMedium"},
        "model_variant": "rfdetr-seg-medium",
        "package": {"name": "rfdetr", "version": "1.9.4"},
        "class_map": {"1": "visible_card"},
        "input_size": [432, 432],
        "confidence_threshold": 0.5,
        "recipe": {**fine_recipe, "recipe_digest": _digest(fine_recipe)},
        "checkpoint_file": fine_checkpoint.name,
        "checkpoint_sha256": hashlib.sha256(fine_checkpoint.read_bytes()).hexdigest(),
        "files": {fine_checkpoint.name: hashlib.sha256(fine_checkpoint.read_bytes()).hexdigest()},
        "initializer_bundle_digest": "c" * 64,
    }
    fine_manifest["bundle_digest"] = _digest(
        {key: value for key, value in fine_manifest.items() if key != "bundle_digest"}
    )
    _write_json(fine / "manifest.json", fine_manifest)
    return coarse, fine


def _request() -> VisibleCardRequest:
    output = BytesIO()
    Image.new("RGB", (100, 80), (80, 90, 100)).save(output, format="PNG")
    return VisibleCardRequest(
        package_id="recording-0071",
        frame_part_name="frame-0001",
        target_offset_ms=0,
        image_bytes=output.getvalue(),
        width=100,
        height=80,
        provider="local-rfdetr-cascade",
        model="local-rfdetr-cascade",
    )


class _CoarseDetector:
    def __init__(self) -> None:
        self.calls = 0

    def predict(self, image: Image.Image, **_kwargs: object) -> object:
        self.calls += 1
        assert image.size == (100, 80)
        return SimpleNamespace(
            xyxy=[[10, 20, 30, 40], [50, 20, 70, 40]],
            confidence=[0.9, 0.8],
            class_id=[0, 0],
        )


class _FineDetector:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def predict(self, image: Image.Image, **_kwargs: object) -> object:
        self.calls.append(image.size)
        return SimpleNamespace(
            xyxy=[[5, 5, 25, 25], [18, 5, 38, 25]],
            confidence=[0.95, 0.9],
            class_id=[0, 0],
            mask=[[[True]], [[True]]],
        )


def test_m6_bundle_verifies_children_and_provider_loads_each_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coarse, fine = _child_bundles(tmp_path / "children")
    bundle_dir = tmp_path / "cascade"
    manifest = assemble_rfdetr_cascade_bundle(
        coarse_bundle=coarse, fine_bundle=fine, output_dir=bundle_dir
    )
    loaded = load_rfdetr_cascade_bundle(bundle_dir)
    assert manifest["schema_version"] == RFDETR_CASCADE_BUNDLE_SCHEMA
    assert loaded.manifest["children"]["coarse"]["model_class"] == "RFDETRSmall"

    monkeypatch.setattr(
        cascade_provider.visible_cards,
        "_mask_to_polygons",
        lambda _mask: [[[5, 5], [25, 5], [25, 25], [5, 25]]],
    )
    coarse_detector = _CoarseDetector()
    fine_detector = _FineDetector()
    load_calls: list[str] = []

    def loader(child: object, _device: str) -> object:
        load_calls.append(child.manifest["model"]["class"])
        return (
            coarse_detector if child.manifest["model"]["class"] == "RFDETRSmall" else fine_detector
        )

    provider = LocalVisibleCardCascadeProvider(
        bundle_dir,
        device="cpu",
        coarse_model_loader=loader,
        fine_model_loader=loader,
    )
    first = provider.propose(_request())
    second = provider.propose(_request())
    assert load_calls == ["RFDETRSmall", "RFDETRSegMedium"]
    assert coarse_detector.calls == 2
    assert fine_detector.calls == [
        (80, 80),
        (80, 80),
    ]
    assert first.status == second.status == "ok"
    assert first.raw_response["coarse"]["layout"] == second.raw_response["coarse"]["layout"]
    assert first.raw_response["reconciliation"] == second.raw_response["reconciliation"]
    assert first.proposals == second.proposals
    assert all(
        prediction["cluster_id"] for prediction in first.raw_response["mapping"]["predictions"]
    )
    assert all(
        candidate["retained_fine_result_id"] == candidate["prediction_id"]
        and candidate["source_transform"]
        for candidate in first.raw_response["candidate_mapping"]
    )


def test_m6_rejects_recipe_or_child_digest_drift(tmp_path: Path) -> None:
    coarse, fine = _child_bundles(tmp_path / "children")
    bundle_dir = tmp_path / "cascade"
    assemble_rfdetr_cascade_bundle(coarse_bundle=coarse, fine_bundle=fine, output_dir=bundle_dir)
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["recipe"]["fine"]["input_size"] = [999, 999]
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RfdetrCascadeBundleError, match="recipe"):
        load_rfdetr_cascade_bundle(bundle_dir)


def test_m6_validation_separates_coarse_misses_from_fine_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coarse, fine = _child_bundles(tmp_path / "children")
    bundle_dir = tmp_path / "cascade"
    assemble_rfdetr_cascade_bundle(coarse_bundle=coarse, fine_bundle=fine, output_dir=bundle_dir)
    monkeypatch.setattr(
        cascade_provider.visible_cards,
        "_mask_to_polygons",
        lambda _mask: [[[5, 5], [25, 5], [25, 25], [5, 25]]],
    )
    provider = LocalVisibleCardCascadeProvider(
        bundle_dir,
        device="cpu",
        coarse_detector=_CoarseDetector(),
        fine_detector=_FineDetector(),
    )
    report_path = tmp_path / "decision.json"
    report = run_rfdetr_cascade_validation(
        provider,
        [
            RfdetrCascadeValidationCase(
                request=_request(),
                target_boxes=(PixelBox(10, 20, 30, 40), PixelBox(50, 20, 70, 40)),
                target_ids=("card-a", "card-b"),
            )
        ],
        output=report_path,
    )
    assert report["status"] == "completed"
    assert report["metrics"]["coarse_stage"]["coarse_stage_miss_count"] == 0
    assert "instance_separation_failure_count" in report["metrics"]["fine_stage"]
    assert json.loads(report_path.read_text(encoding="utf-8"))["report_digest"]
