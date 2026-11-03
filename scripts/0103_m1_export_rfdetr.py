"""Attempt the frozen RF-DETR SegMedium Core ML export for Epic 0103 M1."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / ".runtime/rfdetr-segmentation-0092-m4/bundle"
CHECKPOINT = BUNDLE / "checkpoint_best_total.pth"
OUTPUT = ROOT / ".runtime/0103-m1/rfdetr-seg-medium.mlpackage"
REPORT = ROOT / ".runtime/0103-m1/export-report.json"
EXPECTED_CHECKPOINT_SHA256 = (
    "80accf8a7c55ec65fdd346c0cd2cbfdd28b936260c242c30f1c39ced6043179e"
)
INPUT_SHAPE = (1, 3, 432, 432)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(
        candidate for candidate in path.rglob("*") if candidate.is_file()
    ):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with item.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def write_report(report: dict[str, Any]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def main() -> int:
    sys.path[:0] = [
        str(ROOT / "table_evidence_analyzer/src"),
        str(ROOT / "backend/src"),
    ]
    versions = {
        package: package_version(package)
        for package in (
            "coremltools",
            "rfdetr",
            "torch",
            "torchvision",
            "protobuf",
            "attrs",
            "cattrs",
            "pyaml",
            "sympy",
            "tqdm",
            "packaging",
        )
    }
    report: dict[str, Any] = {
        "schema_version": "epic-0103-m1-rfdetr-export-attempt/v1",
        "status": "failed",
        "platform": platform.platform(),
        "python": sys.version,
        "packages": versions,
        "checkpoint": CHECKPOINT.relative_to(ROOT).as_posix(),
        "expected_checkpoint_sha256": EXPECTED_CHECKPOINT_SHA256,
        "input_shape": list(INPUT_SHAPE),
        "input_contract": "float32 RGB tensor, 432x432, ImageNet-normalized before model",
        "output_contract": ["boxes", "class_logits", "mask_logits"],
        "precision": "float32",
        "minimum_deployment_target": "iOS17",
        "output_package": OUTPUT.relative_to(ROOT).as_posix(),
        "package_digest": None,
    }
    try:
        if not CHECKPOINT.is_file():
            raise FileNotFoundError(
                f"frozen RF-DETR checkpoint is missing: {CHECKPOINT}"
            )
        actual_checkpoint_sha256 = sha256(CHECKPOINT)
        report["checkpoint_sha256"] = actual_checkpoint_sha256
        if actual_checkpoint_sha256 != EXPECTED_CHECKPOINT_SHA256:
            raise RuntimeError("checkpoint digest differs from the frozen M0 artifact")
        if versions["coremltools"] != "9.0":
            raise RuntimeError(
                "install coremltools==9.0 before running the export attempt"
            )

        import coremltools as ct
        import torch
        from table_evidence_analyzer.rfdetr_segmentation_training import (
            load_rfdetr_segmentation_bundle,
        )
        from table_evidence_analyzer.visible_cards import (
            _load_local_rfdetr_segmentation,
        )
        from torch import Tensor, nn

        bundle = load_rfdetr_segmentation_bundle(BUNDLE)
        detector = _load_local_rfdetr_segmentation(bundle, "cpu")

        class ExportOutputs(nn.Module):
            def __init__(self, model: nn.Module) -> None:
                super().__init__()
                self.model = model

            def forward(self, image: Tensor) -> tuple[Tensor, Tensor, Tensor]:
                boxes, logits, masks = self.model(image)
                return boxes, logits, masks

        model = ExportOutputs(detector.model.inference_model.eval()).eval()
        example = torch.zeros(INPUT_SHAPE, dtype=torch.float32)
        with torch.inference_mode():
            expected_outputs = model(example)
        report["traced_output_shapes"] = [
            list(value.shape) for value in expected_outputs
        ]
        traced = torch.jit.trace(model, example, strict=False, check_trace=False)
        coreml_model = ct.convert(
            traced,
            source="pytorch",
            inputs=[ct.TensorType(name="image", shape=INPUT_SHAPE, dtype=float)],
            outputs=[
                ct.TensorType(name="boxes"),
                ct.TensorType(name="class_logits"),
                ct.TensorType(name="mask_logits"),
            ],
            minimum_deployment_target=ct.target.iOS17,
            compute_precision=ct.precision.FLOAT32,
        )
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        coreml_model.save(str(OUTPUT))
        report["status"] = "exported"
        report["package_digest"] = package_sha256(OUTPUT)
        return_code = 0
    except Exception as error:  # noqa: BLE001 - Record any bounded exporter failure for replay.
        report["error_type"] = type(error).__name__
        report["error"] = str(error)
        report["traceback"] = traceback.format_exc()
        return_code = 1
    write_report(report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
